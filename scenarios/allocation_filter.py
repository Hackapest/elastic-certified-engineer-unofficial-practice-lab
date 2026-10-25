from lib.scenariolib import KEEP_REPLICAS, check_cluster_green, check_index_intact, create_index, Scenario

# Filters that leave only one eligible node, so replicas can't be allocated.
# (setting suffix, value, description)
VARIANTS = [
    ("require.zone", "zone-1", "only nodes in zone-1"),
    ("require.temp", "warm", "only warm nodes"),
    ("require._name", "es-a2", "only the node es-a2"),
    ("include._name", "es-a3", "only the node es-a3"),
]


class AllocationFilter(Scenario):
    id = "yellow-index-allocation-filter"
    title = "A yellow cluster after an index-level allocation filter"
    covers = [
        "cluster.health.fix-red-yellow", "cluster.health.allocation-explain", "cluster.health.fix-filtering",
        "cluster.health.cat-apis", "cluster.health.cluster-health", "architecture.allocation.index-filtering",
    ]

    def params(self, rnd, iid):
        setting, value, description = rnd.choice(VARIANTS)
        return {"index": f"orders-{iid}", "setting": f"index.routing.allocation.{setting}", "value": value,
                "description": description, "docs": rnd.randint(200, 900)}

    def cause(self, ctx):
        p = ctx.p
        # A filter added later wouldn't unassign started shards (they just stay put),
        # so the index is created with it: replicas can never be allocated.
        create_index(ctx.es, p["index"], shards=2, replicas=1, settings={p["setting"]: p["value"]},
                     docs=p["docs"], wait="yellow")

    def brief(self, ctx):
        return f"Cluster A is yellow.\n\n{KEEP_REPLICAS}"

    def verify(self, ctx, c):
        p = ctx.p
        check_index_intact(c, ctx.es, p["index"], replicas=1, docs=p["docs"])
        check_cluster_green(c, ctx.es)

    def explain(self, ctx):
        p = ctx.p
        return f"""
Cause: the index {p['index']} has the allocation filter
  {p['setting']}: "{p['value']}"
which allows {p['description']}. A primary and its replica are never allocated to the same
node, so with one eligible node the replicas stay unassigned and the cluster is yellow.

How to find it:
  GET _cluster/health                     -> yellow, unassigned_shards > 0
  GET _cat/shards?v&h=index,shard,prirep,state,node,unassigned.reason
  GET _cluster/allocation/explain         -> the "filter" decider says the node doesn't
                                             match the index's {p['setting']} setting
  GET {p['index']}/_settings              -> shows the filter

Fix it by removing the filter (or widening it), not by dropping replicas.
"""

    def fix(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}/_settings
{{
  "{p['setting']}": null
}}
"""
