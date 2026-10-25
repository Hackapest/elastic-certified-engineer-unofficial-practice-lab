from lib import docker
from lib.scenariolib import Scenario, check_cluster_green, create_index, health
from lib.tasklib import exists, index_settings


class LostNode(Scenario):
    id = "red-lost-node"
    title = "A red index after a node went down"
    covers = [
        "cluster.health.fix-lost-node", "cluster.health.fix-red-yellow", "cluster.health.allocation-explain",
        "cluster.health.cat-apis", "data.index.dynamic-settings",
    ]
    requires = ("shell",)

    def params(self, rnd, iid):
        return {"index": f"ledger-{iid}", "node": rnd.choice(["es-a2", "es-a3"]), "docs": rnd.randint(100, 500)}

    def cause(self, ctx):
        p, es = ctx.p, ctx.es
        # Pin the only copy to the node that will go down, then remove the hint
        create_index(es, p["index"], shards=1, replicas=0, docs=p["docs"],
                     settings={"index.routing.allocation.require._name": p["node"]})
        es.put(f"/{p['index']}/_settings", {"index.routing.allocation.require._name": None})
        docker.compose("stop", p["node"], capture=True)
        es.send("GET", f"/_cluster/health/{p['index']}?wait_for_status=red&timeout=60s")

    def brief(self, ctx):
        return f"""
Cluster A is red.

Fix it so that the cluster is green again and the affected index has all of its documents.
Then make sure that this index stays available if one node goes down in the future.

(Nodes are containers here: `./ece stop`, `./ece start`, `./ece status`.)
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        nodes = es.get("/_cluster/health").get("number_of_nodes")
        c.equal(nodes, 3, "all 3 nodes are in the cluster")
        if not c.check(exists(es, f"/{p['index']}"), f"index {p['index']} still exists"):
            return
        c.equal(health(es, p["index"], 10), "green", f"index {p['index']} is green")
        count = es.send("GET", f"/{p['index']}/_count")[1]
        c.equal((count or {}).get("count"), p["docs"], f"index {p['index']} has all its documents")
        replicas = int((index_settings(es, p["index"]) or {}).get("index.number_of_replicas", 0))
        c.check(replicas >= 1, f"index {p['index']} survives the loss of a node (has a replica)",
                f"it has {replicas} replicas")
        check_cluster_green(c, es)

    def explain(self, ctx):
        p = ctx.p
        return f"""
Cause: the node {p['node']} is down, and it held the only copy of the index {p['index']}
(number_of_replicas: 0). With no copy left in the cluster, the primary can't be allocated:
the index is red and its data is unavailable until the node comes back. The other
indices are only yellow, since their replicas on the lost node are missing.

How to find it:
  GET _cluster/health                     -> red, 2 nodes
  GET _cat/indices?v&health=red
  GET _cluster/allocation/explain         -> "no_valid_shard_copy": cannot allocate because
                                             all found copies of the shard are either stale
                                             or corrupt, or no copy exists in the cluster
  GET _cat/nodes?v                        -> which node is missing

Fix: bring the node back (here: ./ece start {p['node'][3:]}), so the primary can recover from its
data. Never use allocate_empty_primary unless the data is truly lost: it creates an empty
shard and discards the documents. Then add a replica so a single node failure can't make
the index unavailable again.
"""

    def fix(self, ctx):
        return f"""
# First, in a terminal: ./ece start {ctx.p['node'][3:]}

PUT {ctx.p['index']}/_settings
{{
  "number_of_replicas": 1
}}
"""

    def apply_fix(self, ctx):
        docker.compose("start", ctx.p["node"], capture=True)
        ctx.es.send("GET", "/_cluster/health?wait_for_nodes=3&timeout=120s")
        return super().apply_fix(ctx)

    def reset(self, ctx):
        docker.compose("start", ctx.p["node"], capture=True)
        ctx.es.send("GET", "/_cluster/health?wait_for_nodes=3&timeout=120s")
        super().reset(ctx)
