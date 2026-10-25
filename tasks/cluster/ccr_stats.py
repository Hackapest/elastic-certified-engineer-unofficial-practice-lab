import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get  # noqa: E402


class CcrStats(Task):
    id = "cluster-ccr-stats"
    title = "Inspect cross-cluster replication with the follower stats API"
    covers = ["cluster.ccr.stats", "cluster.ccr.follower"]
    answer = "query"
    cluster = "b"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        names = rnd.sample(["orders", "customers", "tickets", "invoices"], 2)
        return {"alias": f"leader_{iid}", "leaders": [f"{n}-{iid}" for n in names],
                "followers": [f"{n}-{iid}-copy" for n in names], "pick": rnd.randrange(2)}

    def setup(self, ctx):
        p = ctx.p
        h.set_remote(ctx.es_b, p["alias"], [h.TRANSPORT_SEED["a"]])
        for leader, follower in zip(p["leaders"], p["followers"]):
            h.bulk(ctx.es_a, leader, h.sales_docs(ctx.iid + leader, "a", 60), h.SALES_MAPPING)
            h.must(ctx.es_b, "PUT", f"/{follower}/_ccr/follow?wait_for_active_shards=1",
                   {"remote_cluster": p["alias"], "leader_index": leader})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster B follows two indices of cluster A: {', '.join(f'`{f}`' for f in p['followers'])}.

Get the shard-level replication statistics (operations read and written, global checkpoints of
leader and follower, ...) of the follower index `{p['followers'][p['pick']]}` only, with the API made
for follower statistics. Run it against cluster B (Kibana B, http://localhost:5602).
"""

    def solution(self, ctx):
        return f"""
GET {ctx.p['followers'][ctx.p['pick']]}/_ccr/stats
"""

    def wrong_answer(self, ctx):
        # Stats of all followers
        return "GET _ccr/stats\n"

    def grade(self, ctx, c, answer, reference):
        want = ctx.p["followers"][ctx.p["pick"]]
        indices = [i.get("index") for i in get(answer, "indices", [])]
        c.check(indices, "the answer is a follower stats response",
                'expected the response of the follower stats API (an "indices" list)')
        c.equal(indices, [want], f"it shows the stats of {want} only")
        shards = get(answer, "indices.0.shards", [])
        c.check(shards and all("leader_global_checkpoint" in s for s in shards), "it shows shard-level stats")

    def cleanup(self, ctx):
        for follower in ctx.p["followers"]:
            ctx.es_b.send("POST", f"/{follower}/_ccr/pause_follow")
        h.full_cleanup(ctx.iid)
