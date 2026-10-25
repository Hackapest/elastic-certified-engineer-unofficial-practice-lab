import json
import random

from lib.tasklib import Task, get
from tasks.ingest._common import MISSING, check_against_reference, render_pipeline

SERVICES = ["checkout", "cart", "search", "payments", "catalog"]
LEVELS = ["INFO", "WARN", "ERROR", "DEBUG"]
MESSAGES = ["Cart total recalculated", "Payment authorized", "Cache miss for key", "Slow query detected",
            "User session refreshed"]


def payload(rnd, prefix):
    data = {f"{prefix}.name": rnd.choice(SERVICES),
            f"{prefix}.version": f"{rnd.randint(1, 3)}.{rnd.randint(0, 9)}.{rnd.randint(0, 20)}",
            "lvl": rnd.choice(LEVELS), "msg": rnd.choice(MESSAGES),
            "ctx": {"user.id": f"u-{rnd.randint(1, 999)}", "user.roles": rnd.sample(["admin", "dev", "ops"], 2)}}
    return json.dumps(data)


def nested(path):
    def value(result):
        v = get(result["source"], path, MISSING)
        return v
    return value


class JsonPipeline(Task):
    id = "ingest-json-pipeline"
    title = "Parse a JSON string, expand dotted keys and move fields (json, dot_expander, rename)"
    covers = ["ingest.pipelines.processor.json", "ingest.pipelines.processor.dot_expander",
              "ingest.pipelines.processor.rename", "ingest.pipelines.processor.lowercase",
              "ingest.pipelines.processor.remove", "ingest.pipelines.simulate"]

    def params(self, rnd, iid):
        prefix = rnd.choice(["svc", "app", "component"])
        return {"pipeline": f"app-json-{iid}", "prefix": prefix,
                "examples": [payload(rnd, prefix) for _ in range(2)]}

    def processors(self, p):
        return [
            {"json": {"field": "payload", "target_field": "parsed"}},
            {"dot_expander": {"field": "*", "path": "parsed"}},
            {"dot_expander": {"field": "*", "path": "parsed.ctx"}},
            {"rename": {"field": f"parsed.{p['prefix']}", "target_field": "service"}},
            {"rename": {"field": "parsed.ctx.user", "target_field": "user"}},
            {"rename": {"field": "parsed.msg", "target_field": "message"}},
            {"rename": {"field": "parsed.lvl", "target_field": "log.level"}},
            {"lowercase": {"field": "log.level"}},
            {"remove": {"field": ["parsed", "payload"]}},
        ]

    def prompt(self, ctx):
        p = ctx.p
        examples = "\n".join(f"  {{ \"payload\": {json.dumps(e)} }}" for e in p["examples"])
        return f"""
An application ships its logs as a JSON string in the field `payload`:

{examples}

Create an ingest pipeline `{p['pipeline']}` that turns each document into exactly this shape
(proper nested objects, not field names containing dots):

  {{
    "service":  {{ "name": ..., "version": ... }},          from {p['prefix']}.name / {p['prefix']}.version
    "user":     {{ "id": ..., "roles": [...] }},            from ctx.user.id / ctx.user.roles
    "message":  ...,                                     from msg
    "log":      {{ "level": ... }}                         from lvl, lowercased
  }}

No other field may remain (in particular not `payload`).
"""

    def solution(self, ctx):
        return render_pipeline(ctx.p["pipeline"], self.processors(ctx.p))

    def verify(self, ctx, c):
        p = ctx.p
        rnd = random.Random()
        docs = [{"payload": payload(rnd, p["prefix"])} for _ in range(6)]
        checks = [(f"{f} is a nested field with the right value", nested(f))
                  for f in ("service.name", "service.version", "user.id", "user.roles", "message", "log.level")]
        checks.append(("no other fields remain", lambda r: sorted(r["source"])))
        check_against_reference(c, ctx.es, p["pipeline"], self.processors(p), docs, checks)
