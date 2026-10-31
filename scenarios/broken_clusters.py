from lib import client, tasklib
from lib.scenariolib import Scenario, check_index_intact, cluster_settings, create_index, health

ENABLE = "cluster.routing.allocation.enable"
EXPLANATIONS = {
    "too-many-replicas": "has more replicas than the cluster has nodes for: at most 2 fit on 3 nodes",
    "index-filter": "has an allocation filter that leaves only one eligible node",
    "shard-limit": "allows only one of its shards per node (total_shards_per_node)",
    "allocation-primaries": "was created while cluster.routing.allocation.enable was set to primaries",
}


class BrokenClusters(Scenario):
    id = "broken-clusters"
    title = "Both clusters have several allocation problems at once"
    covers = ["cluster.health.fix-red-yellow", "cluster.health.allocation-explain", "cluster.health.cat-apis",
              "cluster.health.fix-not-enough-nodes", "cluster.health.fix-filtering", "cluster.health.fix-shard-limits",
              "cluster.health.fix-allocation-disabled"]

    def params(self, rnd, iid):
        kinds = list(EXPLANATIONS)
        rnd.shuffle(kinds)
        names = ["orders", "invoices", "events", "metrics"]
        rnd.shuffle(names)
        # Two problems per cluster, four different ones in total
        problems = [{"cluster": "ab"[i // 2], "kind": kind, "index": f"{names[i]}-{iid}", "docs": rnd.randint(50, 300)}
                    for i, kind in enumerate(kinds)]
        return {"problems": problems}

    def cause(self, ctx):
        for prob in ctx.p["problems"]:
            es, kind, index = client.es(prob["cluster"]), prob["kind"], prob["index"]
            if kind == "too-many-replicas":
                create_index(es, index, shards=1, replicas=4, docs=prob["docs"], wait="yellow")
            elif kind == "index-filter":
                create_index(es, index, shards=2, replicas=1, docs=prob["docs"], wait="yellow",
                             settings={"index.routing.allocation.require.temp": "warm"})
            elif kind == "shard-limit":
                create_index(es, index, shards=3, replicas=1, docs=prob["docs"], wait="yellow",
                             settings={"index.routing.allocation.total_shards_per_node": 1})
            else:
                cluster_settings(es, {ENABLE: "primaries"})
                create_index(es, index, shards=2, replicas=1, docs=prob["docs"], wait="yellow")

    def brief(self, ctx):
        return """
Clusters A and B are both unhealthy; there is more than one problem. Find and fix all of them (use
Kibana A for cluster A and Kibana B for cluster B), so that all non-system indices on both clusters
are green and replicated as much as they can be, without losing any documents. New indices must
be allocated normally too.
"""

    def verify(self, ctx, c):
        for prob in ctx.p["problems"]:
            es = client.es(prob["cluster"])
            replicas = 2 if prob["kind"] == "too-many-replicas" else 1
            check_index_intact(c, es, prob["index"], replicas=replicas, docs=prob["docs"])
        for cluster in "ab":
            c.equal(health(client.es(cluster), wait_seconds=20), "green", f"cluster {cluster.upper()} is green")

    def explain(self, ctx):
        lines = "\n".join(f"  cluster {prob['cluster'].upper()}: {prob['index']} {EXPLANATIONS[prob['kind']]}"
                          for prob in ctx.p["problems"])
        return f"""
Cause: several independent problems:

{lines}

How to find them, on each cluster:
  GET _cat/indices?v&health=yellow        -> the affected indices
  GET _cluster/allocation/explain         -> takes one shard at a time: pass index, shard and
                                             primary in the body to go through all of them
  GET <index>/_settings, GET _cluster/settings
"""

    def fix_for(self, prob):
        index = prob["index"]
        if prob["kind"] == "too-many-replicas":
            return f'PUT {index}/_settings\n{{ "number_of_replicas": 2 }}\n'
        if prob["kind"] == "index-filter":
            return f'PUT {index}/_settings\n{{ "index.routing.allocation.require.temp": null }}\n'
        if prob["kind"] == "shard-limit":
            return f'PUT {index}/_settings\n{{ "index.routing.allocation.total_shards_per_node": null }}\n'
        return f'PUT _cluster/settings\n{{ "persistent": {{ "{ENABLE}": null }} }}\n'

    def fix(self, ctx):
        return "\n".join(f"# On cluster {prob['cluster'].upper()}:\n{self.fix_for(prob)}" for prob in ctx.p["problems"])

    def apply_fix(self, ctx):
        for prob in ctx.p["problems"]:
            _, error = tasklib.run_console(client.es(prob["cluster"]), self.fix_for(prob))
            if error:
                return error
        return None

    def reset(self, ctx):
        for cluster in "ab":
            cluster_settings(client.es(cluster), {ENABLE: None})
            tasklib.cleanup_resources(client.es(cluster), ctx.iid)
