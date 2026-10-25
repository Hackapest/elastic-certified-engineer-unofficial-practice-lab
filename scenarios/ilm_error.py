import time

from lib.scenariolib import Scenario, cluster_settings, create_index
from lib.tasklib import get

POLL = "indices.lifecycle.poll_interval"

# How the rollover alias is broken: (variant, description for explain)
VARIANTS = {
    "no-alias": "the index has no rollover alias at all: neither the alias nor the "
                "index.lifecycle.rollover_alias setting exist",
    "wrong-setting": "index.lifecycle.rollover_alias names an alias that doesn't exist "
                     "(the real alias is spelled differently)",
    "not-write-index": "the alias exists, but the index isn't its write index (is_write_index: false)",
}


class IlmError(Scenario):
    id = "ilm-rollover-error"
    title = "ILM stuck in an error on rollover"
    covers = [
        "cluster.health.fix-ilm", "data.ilm.explain", "data.ilm.rollover-alias",
        "data.aliases.write-index", "data.ilm.action.rollover",
    ]

    def params(self, rnd, iid):
        return {"variant": rnd.choice(sorted(VARIANTS)), "alias": f"applogs-{iid}", "first": f"applogs-{iid}-000001",
                "second": f"applogs-{iid}-000002", "policy": f"rollover-{iid}", "docs": rnd.randint(20, 80)}

    def cause(self, ctx):
        p, es = ctx.p, ctx.es
        cluster_settings(es, {POLL: "1s"})
        es.put(f"/_ilm/policy/{p['policy']}", {"policy": {"phases": {"hot": {"actions": {
            "rollover": {"max_docs": 10}}}}}})
        settings = {"index.lifecycle.name": p["policy"]}
        if p["variant"] == "wrong-setting":
            settings["index.lifecycle.rollover_alias"] = p["alias"].replace("applogs-", "applog-")
        elif p["variant"] == "not-write-index":
            settings["index.lifecycle.rollover_alias"] = p["alias"]
        create_index(es, p["first"], shards=1, replicas=1, settings=settings, docs=p["docs"])
        if p["variant"] != "no-alias":
            es.post("/_aliases", {"actions": [{"add": {"index": p["first"], "alias": p["alias"],
                                                       "is_write_index": p["variant"] != "not-write-index"}}]})
        for _ in range(60):
            if self.step(es, p["first"]) == "ERROR":
                break
            time.sleep(1)

    @staticmethod
    def step(es, index):
        return get(es.get(f"/{index}/_ilm/explain"), f"indices.{index}.step")

    def brief(self, ctx):
        p = ctx.p
        return f"""
Index lifecycle management reports an error for an index on cluster A.

Fix it so that ILM does what the index's policy says: the index must roll over, and
documents written to the alias {p['alias']} must go to the new index. Keep all documents.
(ILM checks every second in this scenario, so you'll see the effect quickly.)
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        for _ in range(20):   # give ILM a moment after a retry
            if es.send("HEAD", f"/{p['second']}")[0] == 200:
                break
            time.sleep(1)
        explain = get(es.get(f"/{p['first']}/_ilm/explain"), f"indices.{p['first']}", {})
        c.check(explain.get("step") != "ERROR", f"ILM has no error for {p['first']}",
                get(explain, "step_info.reason"))
        c.check(es.send("HEAD", f"/{p['second']}")[0] == 200, f"{p['first']} rolled over to {p['second']}")
        aliases = es.send("GET", f"/_alias/{p['alias']}")[1] or {}
        write = [i for i, a in aliases.items() if get(a, f"aliases.{p['alias']}.is_write_index")]
        c.equal(write, [p["second"]], f"the alias {p['alias']} writes to the new index")
        count = es.send("GET", f"/{p['first']}/_count")[1] or {}
        c.equal(count.get("count"), p["docs"], f"{p['first']} still has all its documents")

    def explain(self, ctx):
        p = ctx.p
        return f"""
Cause: the policy {p['policy']} rolls over {p['first']} after 10 documents, but rollover
needs an alias that points to the index as its write index, named by the index setting
index.lifecycle.rollover_alias. Here {VARIANTS[p['variant']]}.
ILM stops in the ERROR step and waits.

How to find it:
  GET */_ilm/explain?only_errors=true     -> the index, the failed step and step_info.reason
  GET _alias/{p['alias']}
  GET {p['first']}/_settings

Fix: make the alias point to the index as write index and set index.lifecycle.rollover_alias
to that alias. This error is auto-retryable (is_auto_retryable_error: true in the explain
output), so ILM retries the step by itself and continues once it's fixed; here within
seconds, normally at the next ILM poll (indices.lifecycle.poll_interval, default 10m).
For errors that aren't retried automatically, POST <index>/_ilm/retry resumes the policy
after the fix; it fails if the index isn't in the ERROR step at that moment.
"""

    def fix(self, ctx):
        p = ctx.p
        return f"""
POST _aliases
{{
  "actions": [
    {{ "add": {{ "index": "{p['first']}", "alias": "{p['alias']}", "is_write_index": true }} }}
  ]
}}

PUT {p['first']}/_settings
{{
  "index.lifecycle.rollover_alias": "{p['alias']}"
}}
"""

    def reset(self, ctx):
        cluster_settings(ctx.es, {POLL: None})
        super().reset(ctx)
