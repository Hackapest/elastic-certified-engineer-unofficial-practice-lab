import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get  # noqa: E402


class CcrFollower(Task):
    id = "cluster-ccr-follower"
    title = "Replicate an index from cluster A to cluster B with a follower index"
    covers = ["cluster.ccr.follower", "cluster.remote.cert-model"]
    answer = "state"
    cluster = "b"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        name = rnd.choice(["orders", "customers", "tickets"])
        return {"alias": f"{rnd.choice(['cluster_a', 'leader', 'dc_main'])}_{iid}", "leader": f"{name}-{iid}",
                "follower": f"{name}-{iid}-{rnd.choice(['replica', 'follower', 'dr'])}",
                "seed": rnd.choice(["es-a1:9300", "es-a2:9300", "es-a3:9300"]),
                "ops": rnd.choice([1000, 2000, 4000]), "docs": rnd.choice([50, 80, 120])}

    def setup(self, ctx):
        h.bulk(ctx.es_a, ctx.p["leader"], h.sales_docs(ctx.iid, "a", ctx.p["docs"]), h.SALES_MAPPING)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster B must hold a live copy of cluster A's index `{p['leader']}`.

On cluster B:
  1. Add cluster A as the persistent remote cluster `{p['alias']}` (certificate-based security,
     sniff mode, seed {p['seed']}).
  2. Create the follower index `{p['follower']}` that replicates `{p['leader']}`, reading at most
     {p['ops']} operations per read request.
  3. Use the CCR stats or follower info APIs to check that it is following and has caught up.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# On cluster B
PUT _cluster/settings
{{
  "persistent": {{
    "cluster.remote.{p['alias']}.seeds": ["{p['seed']}"]
  }}
}}

PUT {p['follower']}/_ccr/follow?wait_for_active_shards=1
{{
  "remote_cluster": "{p['alias']}",
  "leader_index": "{p['leader']}",
  "max_read_request_operation_count": {p['ops']}
}}

GET {p['follower']}/_ccr/info
GET {p['follower']}/_ccr/stats
"""

    def verify(self, ctx, c):
        p, a, b = ctx.p, ctx.es_a, ctx.es_b
        persistent, _ = h.remote_settings(b, p["alias"])
        c.equal(persistent.get("seeds"), [p["seed"]], f"cluster B has the persistent remote {p['alias']}")
        info = h.follow_info(b, p["follower"])
        if not c.check(info, f"{p['follower']} is a follower index"):
            return
        c.equal((info.get("remote_cluster"), info.get("leader_index")), (p["alias"], p["leader"]),
                f"it follows {p['alias']}:{p['leader']}")
        c.equal(info.get("status"), "active", "replication is active")
        c.equal(get(info, "parameters.max_read_request_operation_count"), p["ops"],
                f"it reads at most {p['ops']} operations per request")
        c.equal(h.wait_for(lambda: h.count(b, p["follower"]) == p["docs"], 15) and p["docs"], p["docs"],
                "the follower has all documents of the leader")
        marker = f"check-{int(time.time())}"
        h.send(a, "PUT", f"/{p['leader']}/_doc/{marker}?refresh=true", {"store": marker})
        seen = h.wait_for(lambda: h.send(b, "GET", f"/{p['follower']}/_doc/{marker}")[0] == 200, 20)
        c.check(seen, "a new document in the leader shows up in the follower")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
