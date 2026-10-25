from lib.scenariolib import KEEP_REPLICAS, check_cluster_green, check_index_intact, create_index, Scenario


class TotalShardsPerNode(Scenario):
    id = "yellow-total-shards-per-node"
    title = "A per-index shard limit that leaves replicas unassigned"
    covers = [
        "cluster.health.fix-shard-limits", "architecture.allocation.total-shards-per-node",
        "cluster.health.allocation-explain", "cluster.health.fix-red-yellow",
    ]

    def params(self, rnd, iid):
        return {"index": f"logs-{iid}", "shards": rnd.choice([2, 3]), "docs": rnd.randint(200, 800)}

    def cause(self, ctx):
        p = ctx.p
        create_index(ctx.es, p["index"], shards=p["shards"], replicas=1, docs=p["docs"], wait="yellow",
                     settings={"index.routing.allocation.total_shards_per_node": 1})

    def brief(self, ctx):
        return f"Cluster A is yellow.\n\n{KEEP_REPLICAS}"

    def verify(self, ctx, c):
        p = ctx.p
        check_index_intact(c, ctx.es, p["index"], replicas=1, docs=p["docs"])
        check_cluster_green(c, ctx.es)

    def explain(self, ctx):
        p = ctx.p
        return f"""
Cause: the index {p['index']} has {p['shards']} primaries and 1 replica, so {2 * p['shards']} shards in total,
but index.routing.allocation.total_shards_per_node: 1 allows only one of its shards per node.
With 3 nodes, only 3 of them can be allocated.

How to find it:
  GET _cluster/allocation/explain         -> the "shards_limit" decider: too many shards of
                                             this index on the node
  GET {p['index']}/_settings

Fix: raise the limit to at least {-(-2 * p['shards'] // 3)} (shards / nodes, rounded up), or remove it.
Leaving a little headroom is wise: with exactly the minimum, losing a node leaves shards
unassigned even when other nodes have room.
"""

    def fix(self, ctx):
        return f"""
PUT {ctx.p['index']}/_settings
{{
  "index.routing.allocation.total_shards_per_node": null
}}
"""
