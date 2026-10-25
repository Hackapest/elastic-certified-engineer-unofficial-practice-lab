import random

from lib.tasklib import Task
from tasks.ingest._common import check_against_reference, render_pipeline, simulate

KINDS = ["heartbeat", "event", "alert", "metric"]
LEVELS = ["debug", "info", "warn", "error"]


def event(rnd, drop_kind):
    doc = {"message": rnd.choice(["disk check", "user signed in", "queue drained", "cache warmed"]),
           "level": rnd.choice(LEVELS)}
    r = rnd.random()
    if r < 0.25:
        doc["event"] = {"kind": drop_kind}
    elif r < 0.9:
        doc["event"] = {"kind": rnd.choice([k for k in KINDS if k != drop_kind])}
    if rnd.random() < 0.8:
        doc["user"] = {"id": f"u{rnd.randint(1, 500)}"}
    return doc


class DropFailPipeline(Task):
    id = "ingest-drop-fail-pipeline"
    title = "Drop, reject and short-circuit documents with conditions (drop, fail, terminate, if)"
    covers = ["ingest.pipelines.processor.drop", "ingest.pipelines.processor.fail",
              "ingest.pipelines.processor.terminate", "ingest.pipelines.conditionals",
              "ingest.pipelines.processor.set", "ingest.pipelines.processor.uppercase"]

    def params(self, rnd, iid):
        return {"pipeline": f"events-gate-{iid}", "drop_kind": rnd.choice(["heartbeat", "metric"]),
                "stop_level": rnd.choice(["debug", "info"]),
                "fail_message": rnd.choice(["user.id is required", "missing user id", "no user"])}

    def processors(self, p):
        return [
            {"drop": {"if": f"ctx.event?.kind == '{p['drop_kind']}'"}},
            {"fail": {"if": "ctx.user?.id == null", "message": p["fail_message"]}},
            {"set": {"if": f"ctx.level == '{p['stop_level']}'", "field": "sampled", "value": True}},
            {"terminate": {"if": f"ctx.level == '{p['stop_level']}'"}},
            {"set": {"field": "processed", "value": True}},
            {"uppercase": {"field": "level"}},
        ]

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create an ingest pipeline `{p['pipeline']}` for documents such as

  {{ "message": "disk check", "level": "warn", "event": {{ "kind": "alert" }}, "user": {{ "id": "u12" }} }}

with these rules, in this order:

  1. documents whose event.kind is "{p['drop_kind']}" are silently dropped (not indexed, no error)
  2. any other document without user.id is rejected with the error message "{p['fail_message']}"
  3. documents whose level is "{p['stop_level']}" get the field sampled: true and are then indexed
     as they are, without any further processing
  4. all other documents get processed: true and their level uppercased

Some documents have no `event` object at all: they are not dropped and must not cause errors.
"""

    def solution(self, ctx):
        return render_pipeline(ctx.p["pipeline"], self.processors(ctx.p))

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        rnd = random.Random()
        docs = [event(rnd, p["drop_kind"]) for _ in range(14)]
        docs[0] = {"message": "x", "level": p["stop_level"], "user": {"id": "u1"}}
        docs[1] = {"message": "y", "level": "error", "event": {"kind": p["drop_kind"]}}
        docs[2] = {"message": "z", "level": "warn", "event": {"kind": "alert"}}
        checks = [("sampled is set as requested", "sampled"), ("processed is set as requested", "processed"),
                  ("level is uppercased only when processed", "level")]
        check_against_reference(c, es, p["pipeline"], self.processors(p), docs, checks)
        got, error = simulate(es, [{"message": "m", "level": "warn", "event": {"kind": "alert"}}],
                              pipeline=p["pipeline"])
        if error is None:
            c.check(got[0]["error"] and p["fail_message"] in got[0]["error"],
                    "rejected documents fail with the requested message",
                    f"found: {got[0]['error'] or 'no error'}")
