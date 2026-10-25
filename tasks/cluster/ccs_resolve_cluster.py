import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task  # noqa: E402


def summary(response):
    if not isinstance(response, dict) or not all(isinstance(v, dict) and "connected" in v for v in response.values()):
        return None
    return {k: (v.get("connected"), v.get("matching_indices")) for k, v in response.items()}


class CcsResolveCluster(Task):
    id = "cluster-ccs-resolve-cluster"
    title = "Check remote clusters and matching indices with the resolve cluster API"
    covers = ["search.ccs.resolve-cluster", "cluster.remote.remote-info"]
    answer = "query"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        names = ["east", "west", "north", "south"]
        rnd.shuffle(names)
        return {"up": f"{names[0]}_{iid}", "down": f"{names[1]}_{iid}", "index": f"sales-{iid}",
                "local_has": rnd.choice([True, False])}

    def setup(self, ctx):
        p = ctx.p
        h.bulk(ctx.es_b, f"{p['index']}-2026.09", h.sales_docs(ctx.iid, "b", 10), h.SALES_MAPPING)
        if p["local_has"]:
            h.bulk(ctx.es_a, f"{p['index']}-2026.08", h.sales_docs(ctx.iid, "a", 10), h.SALES_MAPPING)
        h.must(ctx.es, "PUT", "/_cluster/settings", {"persistent": {
            f"cluster.remote.{p['up']}.seeds": [h.TRANSPORT_SEED["b"]],
            f"cluster.remote.{p['down']}.seeds": ["es-b9:9300"],
            f"cluster.remote.{p['down']}.skip_unavailable": True,
        }})
        h.wait_connected(ctx.es, p["up"])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Before running a cross-cluster search over `{p['index']}-*` on the local cluster and the remote
clusters `{p['up']}` and `{p['down']}`, check where it would run.

Hand in one request that reports, for exactly these three clusters (the local one and the two
remotes), whether each is reachable and whether it has indices matching `{p['index']}-*`,
without running a search.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET _resolve/cluster/{p['index']}-*,{p['up']}:{p['index']}-*,{p['down']}:{p['index']}-*
"""

    def grade(self, ctx, c, answer, reference):
        got, want = summary(answer), summary(reference)
        if not c.check(got is not None, "the answer is a resolve cluster response",
                       "use the resolve cluster API (GET _resolve/cluster/...)"):
            return
        c.equal(sorted(got), sorted(want), "it reports exactly the local cluster and the two remotes")
        c.equal(got, want, "it reports reachability and matching indices for each cluster")

    def wrong_answer(self, ctx):
        p = ctx.p
        return f"GET _resolve/cluster/{p['up']}:{p['index']}-*,{p['down']}:{p['index']}-*\n"

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
