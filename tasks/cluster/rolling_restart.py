import time

from lib import nodes
from lib.tasklib import Task, get

ENABLE = "cluster.routing.allocation.enable"


class RollingRestart(Task):
    id = "cluster-rolling-restart"
    title = "Rolling restart of a cluster without unnecessary shard movement"
    covers = ["cluster.maintenance.rolling-restart", "architecture.allocation.allocation-enable",
              "cluster.health.cluster-settings"]
    answer = "state"
    cluster = "b"
    requires = ("shell",)

    def params(self, rnd, iid):
        return {}

    def setup(self, ctx):
        ctx.p["started_ms"] = int(time.time() * 1000)

    def prompt(self, ctx):
        return """
Cluster B needs a rolling restart: restart its three nodes one after the other (`./ece restart b1`,
then b2, then b3), so that the cluster stays available the whole time. Follow the procedure that
avoids needless shard copying:

  - before each restart, stop replicas from being reallocated (primaries may still be allocated),
    and flush the data to disk
  - after the node is back, allow all allocation again and wait for the cluster to recover
    before you restart the next node

At the end, every node of cluster B must have been restarted, allocation must be fully enabled
again (the default), and the cluster green.
"""

    def solution(self, ctx):
        return """
# For each node (b1, then b2, then b3):
PUT _cluster/settings
{ "persistent": { "cluster.routing.allocation.enable": "primaries" } }

POST _flush

# ./ece restart b1    (then b2, b3)

GET _cat/nodes?v            # wait until the node is back

PUT _cluster/settings
{ "persistent": { "cluster.routing.allocation.enable": null } }

GET _cluster/health?wait_for_status=green&timeout=60s
"""

    def apply_solution(self, ctx):
        es = ctx.es
        for node in nodes.CLUSTER_NODES["b"]:
            es.put("/_cluster/settings", {"persistent": {ENABLE: "primaries"}})
            es.send("POST", "/_flush")
            if not nodes.restart(node):
                return f"{node} didn't rejoin"
            es.put("/_cluster/settings", {"persistent": {ENABLE: None}})
            es.send("GET", "/_cluster/health?wait_for_status=green&timeout=90s", timeout=120)
        return None

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        starts = nodes.start_times("b")
        stale = [n for n, t in starts.items() if t < p["started_ms"]]
        c.check(len(starts) == 3 and not stale, "every node of cluster B was restarted",
                f"not restarted since the task began: {', '.join(sorted(stale)) or '-'}; nodes: {len(starts)}")
        flat = get(es.get("/_cluster/settings?flat_settings=true"), "persistent", {})
        c.check(flat.get(ENABLE) in (None, "all"), "allocation is fully enabled again",
                f"{ENABLE} is {flat.get(ENABLE)!r}")
        health = es.send("GET", "/_cluster/health?wait_for_status=green&timeout=90s", timeout=120)[1] or {}
        c.equal(health.get("status"), "green", "cluster B is green")

    def cleanup(self, ctx):
        ctx.es.put("/_cluster/settings", {"persistent": {ENABLE: None}})
