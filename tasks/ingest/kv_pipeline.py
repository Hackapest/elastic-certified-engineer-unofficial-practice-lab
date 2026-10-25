import random

from lib.tasklib import Task
from tasks.ingest._common import check_against_reference, render_pipeline

USERS = ["Alice", "bob", "Carol", "DAVE", "erin", "Frank"]
ACTIONS = ["LOGIN", "Logout", "upload", "Download", "DELETE"]
ROLES = ["admin", "dev", "ops", "audit", "sales"]
UNITS = ["b", "kb", "mb", "gb"]
# (displayed separator, kv field_split regex)
SEPARATORS = [(";", ";"), ("&", "&"), ("|", "\\|")]


def raw_line(rnd, sep):
    size = f"{rnd.randint(1, 900)}{rnd.choice(UNITS)}"
    roles = ",".join(rnd.sample(ROLES, rnd.randint(1, 3)))
    pairs = [f"user={rnd.choice(USERS)}", f"action={rnd.choice(ACTIONS)}", f"roles={roles}", f"size={size}"]
    rnd.shuffle(pairs)
    return f" {sep} ".join(" " * rnd.randint(0, 1) + p for p in pairs) + " " * rnd.randint(0, 2)


class KvPipeline(Task):
    id = "ingest-kv-pipeline"
    title = "Parse key=value pairs and clean up the values (kv, split, lowercase, trim, bytes)"
    covers = ["ingest.pipelines.processor.kv", "ingest.pipelines.processor.split",
              "ingest.pipelines.processor.lowercase", "ingest.pipelines.processor.trim",
              "ingest.pipelines.processor.bytes", "ingest.pipelines.processor.remove",
              "ingest.pipelines.create", "ingest.pipelines.simulate"]

    def params(self, rnd, iid):
        sep = rnd.choice(SEPARATORS)
        return {"pipeline": f"audit-kv-{iid}", "sep": sep[0], "regex": sep[1],
                "target": rnd.choice(["audit", "event_data"]),
                "examples": [raw_line(rnd, sep[0]) for _ in range(2)]}

    def processors(self, p):
        t = p["target"]
        return [
            {"kv": {"field": "raw", "field_split": p["regex"], "value_split": "=", "target_field": t,
                    "trim_key": " ", "trim_value": " "}},
            {"lowercase": {"field": f"{t}.user"}},
            {"lowercase": {"field": f"{t}.action"}},
            {"split": {"field": f"{t}.roles", "separator": ","}},
            {"bytes": {"field": f"{t}.size"}},
            {"remove": {"field": "raw"}},
        ]

    def prompt(self, ctx):
        p = ctx.p
        examples = "\n".join(f'  "raw": "{e}"' for e in p["examples"])
        return f"""
An audit system sends documents with a single field `raw` holding key=value pairs separated by
`{p['sep']}`, with stray spaces around the pairs:

{examples}

Create an ingest pipeline `{p['pipeline']}` that produces, under the object `{p['target']}`:

  {p['target']}.user     the user, lowercased, without surrounding spaces
  {p['target']}.action   the action, lowercased, without surrounding spaces
  {p['target']}.roles    an array with one element per role (the roles are comma-separated)
  {p['target']}.size     the size converted to a number of bytes (e.g. "2kb" becomes 2048)

and removes the `raw` field. Keys and values must not keep any leading or trailing spaces.
Test the pipeline with the simulate API.
"""

    def solution(self, ctx):
        return render_pipeline(ctx.p["pipeline"], self.processors(ctx.p))

    def verify(self, ctx, c):
        p = ctx.p
        rnd = random.Random()
        docs = [{"raw": raw_line(rnd, p["sep"])} for _ in range(8)]
        t = p["target"]
        checks = [(f"{t}.{f} is extracted as requested", f"{t}.{f}") for f in ("user", "action", "roles", "size")]
        checks.append(("raw is removed", "raw"))
        check_against_reference(c, ctx.es, p["pipeline"], self.processors(p), docs, checks)
