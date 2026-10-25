from lib.tasklib import Task, index_settings


class AllocationDelayTiers(Task):
    id = "architecture-allocation-delay-tiers"
    title = "Delay reallocation after a node leaves, and prefer data tiers"
    covers = ["architecture.allocation.delayed-allocation", "architecture.allocation.tier-preference",
              "data.index.dynamic-settings"]
    answer = "state"

    def params(self, rnd, iid):
        tiers = rnd.choice([["data_warm", "data_hot"], ["data_cold", "data_warm", "data_hot"], ["data_hot"]])
        return {"index": f"ledger-{iid}", "new": f"ledger-archive-{iid}", "delay": rnd.choice(["3m", "5m", "10m"]),
                "tiers": tiers}

    def setup(self, ctx):
        ctx.es.put(f"/{ctx.p['index']}", {"settings": {"number_of_shards": 2, "number_of_replicas": 1}})

    def prompt(self, ctx):
        p = ctx.p
        order = " if available, otherwise ".join(t.replace("data_", "") for t in p["tiers"])
        return f"""
  1. When a node holding shards of the existing index `{p['index']}` leaves the cluster, its
     replicas must not be reallocated to other nodes until the node has been gone for {p['delay']}
     (so a quick restart doesn't trigger a full copy).
  2. Create the index `{p['new']}` (1 shard, 1 replica) whose shards go to the {order} tier.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}/_settings
{{
  "index.unassigned.node_left.delayed_timeout": "{p['delay']}"
}}

PUT {p['new']}
{{
  "settings": {{
    "number_of_shards": 1,
    "number_of_replicas": 1,
    "index.routing.allocation.include._tier_preference": "{','.join(p['tiers'])}"
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        s = index_settings(es, p["index"]) or {}
        c.equal(s.get("index.unassigned.node_left.delayed_timeout"), p["delay"],
                f"{p['index']} delays reallocation by {p['delay']}")
        s = index_settings(es, p["new"])
        if c.check(s is not None, f"index {p['new']} exists"):
            c.equal(s.get("index.routing.allocation.include._tier_preference"), ",".join(p["tiers"]),
                    "its tier preference (in that order)")
