import json
import random

from lib.tasklib import Task, get

LEVELS = ["INFO", "WARN", "ERROR", "DEBUG"]
SERVICES = ["payment-service", "cart-api", "auth-gateway", "search-worker"]
REASONS = ["Timeout after 3000 ms", "Connection refused", "Cache miss for key user:42", "Retrying request 2 of 5"]
KIBANA_HEADERS = {"elastic-api-version": "2023-10-31"}


def line(rnd):
    return {"level": rnd.choice(LEVELS), "service": rnd.choice(SERVICES), "reason": rnd.choice(REASONS),
            "time": f"2026-10-{rnd.randint(1, 28):02d}T{rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:00Z"}


def render(entry, separator):
    return separator.join([entry["time"], entry["level"], entry["service"], entry["reason"]])


class StreamsProcessing(Task):
    id = "ingest-streams-processing"
    title = "Parse log lines with Streams processing (classic stream)"
    covers = ["ingest.streams.process", "ingest.streams.classic", "ingest.streams.api",
              "ingest.pipelines.processor.dissect", "ingest.pipelines.processor.grok"]
    answer = "state"
    requires = ("kibana",)

    def params(self, rnd, iid):
        return {"stream": f"appevents-{iid}", "template": f"appevents-{iid}",
                "separator": rnd.choice([" ", " | "]),
                "fields": rnd.choice([("log.level", "service.name", "event.reason"),
                                      ("severity", "service", "reason")]),
                "examples": [line(rnd) for _ in range(3)]}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/_index_template/{p['template']}", {"index_patterns": [f"{p['stream']}*"], "data_stream": {},
                                                     "priority": 500})
        es.put(f"/_data_stream/{p['stream']}")
        bulk = "".join(json.dumps({"create": {}}) + "\n" +
                       json.dumps({"@timestamp": e["time"], "message": render(e, p["separator"])}) + "\n"
                       for e in p["examples"])
        es.send("POST", f"/{p['stream']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        level, service, reason = p["fields"]
        examples = "\n".join(f"  {render(e, p['separator'])}" for e in p["examples"])
        return f"""
The data stream `{p['stream']}` on cluster A receives application log lines in its `message` field:

{examples}

In Kibana A, manage it as a (classic) stream: open Streams, select `{p['stream']}`, and add
processing so that every new document gets these fields extracted from `message`:

  {level:<14} INFO, WARN, ...
  {service:<14} the service name
  {reason:<14} the rest of the line after the service name

Use the processing preview to check it on the existing documents, then save it.
(Streams is in the Kibana menu; the Streams API, e.g. via `PUT kbn:/api/streams/...` in
Dev Tools, works too.)
"""

    def pattern(self, p):
        level, service, reason = p["fields"]
        s = p["separator"]
        return s.join(["%{?time}", f"%{{{level}}}", f"%{{{service}}}", f"%{{{reason}}}"])

    def body(self, p):
        return {"ingest": {"lifecycle": {"inherit": {}}, "settings": {}, "classic": {},
                           "failure_store": {"inherit": {}},
                           "processing": {"steps": [{"action": "dissect", "from": "message",
                                                     "pattern": self.pattern(p)}]}}}

    def solution(self, ctx):
        p = ctx.p
        return f"""
# In Kibana: Streams -> {p['stream']} -> Processing -> add a Dissect processor on "message"
# with the pattern below, check the preview, save. The same with the Streams API:

PUT kbn:/api/streams/{p['stream']}/_ingest
{json.dumps(self.body(p), indent=2)}
"""

    def apply_solution(self, ctx):
        status, response = ctx.kibana().send("PUT", f"/api/streams/{ctx.p['stream']}/_ingest",
                                             json.dumps(self.body(ctx.p)).encode(), "application/json")
        return None if status == 200 else str(response)[:300]

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        kibana = ctx.kibana()
        kibana.headers.update(KIBANA_HEADERS)
        status, stream = kibana.send("GET", f"/api/streams/{p['stream']}")
        if not c.check(status == 200, f"{p['stream']} is a stream in Kibana", str(stream)[:200]):
            return
        steps = get(stream, "stream.ingest.processing.steps", [])
        c.check(steps, "the stream has processing steps (defined in Streams)")
        level, service, reason = p["fields"]
        sample = line(random.Random())
        doc = {"@timestamp": sample["time"], "message": render(sample, p["separator"])}
        status, response = es.send("POST", f"/{p['stream']}/_doc?refresh=true", json.dumps(doc).encode(),
                                   "application/json")
        if not c.check(status in (200, 201), "a new document can be written to the stream", str(response)[:200]):
            return
        index, doc_id = response["_index"], response["_id"]
        source = es.get(f"/{index}/_doc/{doc_id}")["_source"]
        es.send("DELETE", f"/{index}/_doc/{doc_id}?refresh=true")

        def value(field):   # flat ("log.level") or nested ({"log": {"level": ...}}) both count
            return source.get(field, get(source, field))
        for field, want in ((level, sample["level"]), (service, sample["service"]), (reason, sample["reason"])):
            got = value(field)
            c.check(got == want, f"new documents get {field}", f"for {doc['message']!r}: expected {want!r}, got {got!r}")

    def cleanup(self, ctx):
        kibana = ctx.kibana()
        kibana.headers.update(KIBANA_HEADERS)
        kibana.send("DELETE", f"/api/streams/{ctx.p['stream']}")
