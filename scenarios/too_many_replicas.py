from lib.scenariolib import check_cluster_green, check_index_intact, create_index, Scenario


class TooManyReplicas(Scenario):
    id = "yellow-too-many-replicas"
    title = "More replicas than the cluster can hold"
    covers = [
        "cluster.health.fix-not-enough-nodes", "cluster.health.allocation-explain",
        "cluster.health.fix-red-yellow", "data.index.dynamic-settings",
    ]

    def params(self, rnd, iid):
        return {"index": f"metrics-{iid}", "replicas": rnd.choice([3, 4]), "shards": rnd.choice([1, 2, 3]),
                "docs": rnd.randint(100, 600)}

    def cause(self, ctx):
        p = ctx.p
        create_index(ctx.es, p["index"], shards=p["shards"], replicas=p["replicas"], docs=p["docs"],
                     wait="yellow")

    def brief(self, ctx):
        return """
Cluster A is yellow.

Fix it so that the cluster is green again, without losing any documents, and so that
every index keeps as many replicas as this cluster can actually hold.
"""

    def verify(self, ctx, c):
        p = ctx.p
        # 3 nodes hold at most 3 copies of a shard: 1 primary + 2 replicas
        check_index_intact(c, ctx.es, p["index"], replicas=2, docs=p["docs"])
        check_cluster_green(c, ctx.es)

    def explain(self, ctx):
        p = ctx.p
        return f"""
Cause: the index {p['index']} has number_of_replicas: {p['replicas']}. A shard and its copies
must all be on different nodes, so on 3 nodes at most 1 primary + 2 replicas can be
allocated; the rest stay unassigned and the cluster is yellow.

How to find it:
  GET _cat/indices?v&health=yellow        -> the affected index
  GET _cluster/allocation/explain         -> the "same_shard" decider: a copy of this shard
                                             is already allocated to every node

Fix: lower the replicas to 2, the most this cluster can hold. (Adding nodes would also fix
it.) "auto_expand_replicas": "0-all" is another option that adapts to the node count.
"""

    def fix(self, ctx):
        return f"""
PUT {ctx.p['index']}/_settings
{{
  "number_of_replicas": 2
}}
"""
