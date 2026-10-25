import random

from lib.tasklib import Task
from tasks.ingest._common import check_against_reference, field, render_pipeline

SERVICES = ["payment", "search", "auth", "billing"]


def line(rnd, sep):
    kind = rnd.random()
    ts = f"2026-0{rnd.randint(1, 9)}-1{rnd.randint(0, 9)}T{rnd.randint(10, 23)}:{rnd.randint(10, 59)}:00Z"
    duration = str(rnd.randint(1, 900))
    if kind < 0.15:
        ts = rnd.choice(["yesterday", "31/31/2026", "n/a"])
    elif kind < 0.3:
        duration = rnd.choice(["n/a", "slow", "-"])
    doc = {"message": sep.join([ts, rnd.choice(["INFO", "WARN", "ERROR"]), rnd.choice(SERVICES), duration])}
    if kind > 0.9:
        doc["message"] = rnd.choice(["garbage", "connection reset by peer", ""])
    if rnd.random() < 0.5:
        doc["legacy_host"] = f"web-{rnd.randint(1, 9)}"
    return doc


def error_set(r):
    v = field(r["source"], "error.message")
    return isinstance(v, str) and len(v) > 0


class OnFailurePipeline(Task):
    id = "ingest-on-failure-pipeline"
    title = "Handle failures in a pipeline (on_failure, ignore_missing, failure index)"
    covers = ["ingest.pipelines.on-failure", "ingest.pipelines.metadata-access",
              "ingest.pipelines.processor.dissect", "ingest.pipelines.processor.date",
              "ingest.pipelines.processor.convert", "ingest.pipelines.processor.rename"]

    def params(self, rnd, iid):
        sep = rnd.choice(["|", " ; ", ","])
        return {"pipeline": f"svc-logs-{iid}", "failed": f"failed-svc-logs-{iid}", "sep": sep,
                "examples": [line(random.Random(n), sep)["message"] for n in (3, 8)]}

    def processors(self, p):
        return [
            {"dissect": {"field": "message", "pattern": p["sep"].join(
                ["%{ts}", "%{log.level}", "%{service.name}", "%{duration_ms}"])}},
            {"date": {"field": "ts", "formats": ["ISO8601"]}},
            {"convert": {"field": "duration_ms", "type": "integer",
                         "on_failure": [{"remove": {"field": "duration_ms"}}]}},
            {"rename": {"field": "legacy_host", "target_field": "host.name", "ignore_missing": True}},
            {"remove": {"field": "ts"}},
        ], [
            {"set": {"field": "error.message", "value": "{{{_ingest.on_failure_message}}}"}},
            {"set": {"field": "_index", "value": p["failed"]}},
        ]

    def prompt(self, ctx):
        p = ctx.p
        examples = "\n".join(f'  "message": "{e}"' for e in p["examples"])
        return f"""
Service logs arrive in `message` as four values separated by "{p['sep']}": an ISO 8601
timestamp, a level, a service name and a duration in milliseconds:

{examples}

Some documents also have a `legacy_host` field. Create an ingest pipeline `{p['pipeline']}` that:

  - extracts @timestamp (parsed as a date), log.level, service.name and duration_ms (an integer)
    and keeps no other new fields (no leftover temporary field)
  - moves legacy_host to host.name when it is present; documents without it must not fail
  - when the duration is not a number (e.g. "n/a"), simply removes duration_ms and goes on
  - when anything else fails (the message doesn't match, the timestamp can't be parsed), does
    not reject the document: stores the failure message in error.message and sends the document
    to the index `{p['failed']}` instead
"""

    def solution(self, ctx):
        processors, on_failure = self.processors(ctx.p)
        return render_pipeline(ctx.p["pipeline"], processors, {"on_failure": on_failure})

    def verify(self, ctx, c):
        p = ctx.p
        rnd = random.Random()
        docs = [line(rnd, p["sep"]) for _ in range(16)]
        docs[0] = {"message": p["sep"].join(["2026-02-03T04:05:06Z", "WARN", "auth", "n/a"])}
        docs[1] = {"message": p["sep"].join(["sometime", "WARN", "auth", "12"]), "legacy_host": "web-1"}
        docs[2] = {"message": "no separators here"}
        docs[3] = {"message": p["sep"].join(["2026-02-03T04:05:06Z", "INFO", "search", "15"]), "legacy_host": "w"}
        processors, on_failure = self.processors(p)

        def parsed(path):
            return lambda r: field(r["source"], path) if r["index"] != p["failed"] else "(failed)"

        checks = [("failed documents go to the failure index", lambda r: r["index"] == p["failed"]),
                  ("failed documents carry error.message",
                   lambda r: error_set(r) if r["index"] == p["failed"] else "(not failed)")]
        checks += [(f"{f} is extracted as requested", parsed(f))
                   for f in ("@timestamp", "log.level", "service.name", "duration_ms", "host.name")]
        checks.append(("no other fields are added",
                       lambda r: sorted(k for k in r["source"] if k != "error") if r["index"] != p["failed"]
                       else "(failed)"))
        check_against_reference(c, ctx.es, p["pipeline"], {"processors": processors, "on_failure": on_failure},
                                docs, checks)
