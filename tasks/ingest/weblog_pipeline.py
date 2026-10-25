import json
import random
from datetime import datetime, timedelta, timezone

from lib.tasklib import Task, get

METHODS = ["GET", "POST", "PUT", "DELETE"]
PATHS = ["/", "/cart", "/checkout", "/api/v1/items", "/login", "/static/app.js"]
USERS = ["alice", "bob", "carol", "dave", "-"]
STATUSES = [200, 201, 204, 301, 304, 400, 401, 403, 404, 500, 502, 503]


def log_line(rnd):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=rnd.randrange(300 * 86400))
    entry = {
        "ip": f"{rnd.randint(1, 223)}.{rnd.randint(0, 255)}.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}",
        "user": rnd.choice(USERS),
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": rnd.choice(METHODS),
        "path": rnd.choice(PATHS),
        "status": rnd.choice(STATUSES),
        "bytes": rnd.randint(0, 50000),
    }
    entry["line"] = (f'{entry["ip"]} - {entry["user"]} [{entry["ts"]}] '
                     f'"{entry["method"]} {entry["path"]} HTTP/1.1" {entry["status"]} {entry["bytes"]}')
    return entry


def same_instant(value, iso):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed == datetime.fromisoformat(iso.replace("Z", "+00:00"))


class WeblogPipeline(Task):
    id = "ingest-weblog-pipeline"
    title = "Parse web server log lines with an ingest pipeline"
    covers = [
        "ingest.pipelines.create", "ingest.pipelines.simulate", "ingest.pipelines.parse-logs",
        "ingest.pipelines.conditionals", "ingest.pipelines.processor.dissect", "ingest.pipelines.processor.grok",
        "ingest.pipelines.processor.convert", "ingest.pipelines.processor.date", "ingest.pipelines.processor.set", "ingest.pipelines.processor.remove",
    ]
    answer = "state"

    def params(self, rnd, iid):
        return {
            "pipeline": f"weblogs-{iid}",
            "threshold": rnd.choice([400, 500]),
            "examples": [log_line(rnd)["line"] for _ in range(2)],
        }

    def prompt(self, ctx):
        p = ctx.p
        examples = "\n".join(f"  {line}" for line in p["examples"])
        return f"""
Documents arrive with a single field `message` holding a web server log line, like:

{examples}

Create an ingest pipeline named `{p['pipeline']}` that turns the message into these fields:

  source.ip                        the client IP
  user.name                        the user (the third value; "-" when anonymous)
  http.request.method              GET, POST, ...
  url.path                         the requested path
  http.response.status_code        the status code, as an integer
  http.response.body.bytes         the response size, as a long
  @timestamp                       the time in brackets, parsed as a date

It must also set `event.outcome` to "failure" when the status code is {p['threshold']} or higher,
and to "success" otherwise, and remove the `message` field.

Test it with the simulate API before you hand it in.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _ingest/pipeline/{p['pipeline']}
{{
  "processors": [
    {{
      "dissect": {{
        "field": "message",
        "pattern": "%{{source.ip}} - %{{user.name}} [%{{log_time}}] \\"%{{http.request.method}} %{{url.path}} %{{?http_version}}\\" %{{http.response.status_code}} %{{http.response.body.bytes}}"
      }}
    }},
    {{ "convert": {{ "field": "http.response.status_code", "type": "integer" }} }},
    {{ "convert": {{ "field": "http.response.body.bytes", "type": "long" }} }},
    {{ "date": {{ "field": "log_time", "formats": ["ISO8601"] }} }},
    {{
      "set": {{
        "if": "ctx.http.response.status_code >= {p['threshold']}",
        "field": "event.outcome",
        "value": "failure"
      }}
    }},
    {{
      "set": {{
        "if": "ctx.http.response.status_code < {p['threshold']}",
        "field": "event.outcome",
        "value": "success"
      }}
    }},
    {{ "remove": {{ "field": ["message", "log_time"] }} }}
  ]
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = es.send("GET", f"/_ingest/pipeline/{p['pipeline']}")
        if not c.check(status == 200, f"pipeline {p['pipeline']} exists"):
            return
        # Fresh log lines the user hasn't seen, plus both outcomes for sure
        rnd = random.Random()
        samples = [log_line(rnd) for _ in range(8)]
        samples[0]["status"], samples[1]["status"] = 200, p["threshold"]
        for s in samples[:2]:
            s["line"] = (f'{s["ip"]} - {s["user"]} [{s["ts"]}] '
                         f'"{s["method"]} {s["path"]} HTTP/1.1" {s["status"]} {s["bytes"]}')
        status, response = es.send(
            "POST", f"/_ingest/pipeline/{p['pipeline']}/_simulate",
            data=json.dumps({"docs": [{"_source": {"message": s["line"]}} for s in samples]}).encode(),
            content_type="application/json")
        if not c.check(status == 200, "the pipeline can be simulated", str(response)[:300]):
            return

        problems = {}
        for s, doc in zip(samples, response["docs"]):
            if "error" in doc:
                problems.setdefault("the pipeline processes every sample without errors",
                                    f"{s['line']} -> {get(doc, 'error.reason')}")
                continue
            src = get(doc, "doc._source", {})
            expected = [
                ("source.ip", s["ip"]), ("user.name", s["user"]), ("http.request.method", s["method"]),
                ("url.path", s["path"]), ("http.response.status_code", s["status"]),
                ("http.response.body.bytes", s["bytes"]),
                ("event.outcome", "failure" if s["status"] >= p["threshold"] else "success"),
            ]
            for field, want in expected:
                got = get(src, field)
                if got != want:
                    problems.setdefault(f"{field} is extracted correctly",
                                        f"for '{s['line']}': expected {want!r}, found {got!r}")
            if not same_instant(src.get("@timestamp"), s["ts"]):
                problems.setdefault("@timestamp is parsed from the log line",
                                    f"for '{s['line']}': found {src.get('@timestamp')!r}")
            if "message" in src:
                problems.setdefault("message is removed", "the output still has a message field")

        checks = ["the pipeline processes every sample without errors"] + \
            [f"{f} is extracted correctly" for f in ("source.ip", "user.name", "http.request.method", "url.path",
                                                     "http.response.status_code", "http.response.body.bytes",
                                                     "event.outcome")] + \
            ["@timestamp is parsed from the log line", "message is removed"]
        for check in checks:
            c.check(check not in problems, check, problems.get(check))
