from lib.scenariolib import check_cluster_green, check_index_intact, cluster_settings, Scenario


class ClusterShardLimit(Scenario):
    id = "cluster-shard-limit"
    title = "New indices are rejected by the cluster-wide shard limit"
    covers = [
        "cluster.health.fix-shard-limits", "architecture.allocation.cluster-shard-limit",
        "cluster.health.cluster-settings",
    ]

    def params(self, rnd, iid):
        return {"index": f"invoices-{iid}", "shards": rnd.choice([1, 2])}

    def cause(self, ctx):
        es = ctx.es
        open_shards = es.get("/_cluster/health")["active_shards"]
        ctx.p["indices_before"] = sorted(i["index"] for i in es.get("/_cat/indices?format=json&h=index"))
        # Below the current number of open shards: nothing new fits
        cluster_settings(es, {"cluster.max_shards_per_node": max(1, open_shards // 3 - 2)})

    def request(self, ctx):
        return f"""
PUT {ctx.p['index']}
{{
  "settings": {{ "number_of_shards": {ctx.p['shards']}, "number_of_replicas": 1 }}
}}"""

    def brief(self, ctx):
        return f"""
An application can't create its index on cluster A. It sends:
{self.request(ctx)}

Run it yourself to see the error. Fix the cluster so that this request succeeds and the
index turns green, without deleting or closing any existing index.
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        check_index_intact(c, es, p["index"], replicas=1, docs=0)
        now = {i["index"] for i in es.get("/_cat/indices?format=json&h=index")}
        missing = [i for i in p["indices_before"] if i not in now and not i.startswith("probe-")]
        c.check(not missing, "no existing index was deleted",
                f"missing: {', '.join(missing[:5])}")
        closed = [i["index"] for i in es.get("/_cat/indices?format=json&h=index,status") if i["status"] == "close"]
        c.check(not closed, "no index is closed", f"closed: {', '.join(closed[:5])}")
        check_cluster_green(c, es)

    def explain(self, ctx):
        return """
Cause: the persistent cluster setting cluster.max_shards_per_node is lower than the number
of shards already open in the cluster. Every request that would add shards (creating an
index, adding replicas, opening a closed index) is rejected with "this action would add
[N] shards, but this cluster currently has [X]/[Y] maximum normal shards open". The limit
is cluster.max_shards_per_node x number of data nodes; the default is 1000 per node.

How to find it:
  The error message of the request names the limit.
  GET _cluster/settings                   -> shows cluster.max_shards_per_node
  GET _cluster/health                     -> active_shards: how many are open

Fix: raise the limit (or remove it to get the default back), then create the index.
Deleting or closing indices would also free up room, but the task rules that out.
"""

    def fix(self, ctx):
        return """
PUT _cluster/settings
{
  "persistent": {
    "cluster.max_shards_per_node": null
  }
}
""" + self.request(ctx)

    def reset(self, ctx):
        cluster_settings(ctx.es, {"cluster.max_shards_per_node": None})
        super().reset(ctx)
