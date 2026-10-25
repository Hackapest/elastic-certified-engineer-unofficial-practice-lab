import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.sampledata import FLIGHTS  # noqa: E402
from lib.tasklib import Task, get  # noqa: E402


class CcsSkipUnavailable(Task):
    id = "cluster-ccs-skip-unavailable"
    title = "Keep cross-cluster searches working when an optional remote is down"
    covers = ["search.ccs.options", "cluster.remote.settings", "cluster.remote.remote-info"]
    answer = "state"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        return {"primary": f"{rnd.choice(['primary', 'main', 'core'])}_{iid}",
                "optional": f"{rnd.choice(['archive', 'backup', 'lab'])}_{iid}",
                "dead": rnd.choice(["es-b7:9300", "es-b8:9300", "es-b9:9300"])}

    def search_path(self, p):
        return f"/{FLIGHTS},{p['primary']}:{FLIGHTS},{p['optional']}:{FLIGHTS}/_search"

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        h.must(es, "PUT", "/_cluster/settings", {"persistent": {
            f"cluster.remote.{p['primary']}.seeds": [h.TRANSPORT_SEED["b"]],
            f"cluster.remote.{p['primary']}.skip_unavailable": True,
            f"cluster.remote.{p['optional']}.seeds": [p["dead"]],
            f"cluster.remote.{p['optional']}.skip_unavailable": False,
        }})
        h.wait_connected(es, p["primary"])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
A dashboard on cluster A runs this search over the local cluster and two remote clusters:

GET {self.search_path(p)[1:]}
{{ "size": 0 }}

`{p['optional']}` is an optional archive cluster that is down at the moment (and its seed
{p['dead']} is not reachable), and the search fails. Find out with the resolve cluster API which
remote is the problem. Then, without removing either remote cluster or changing its seeds:

  - make the search succeed while `{p['optional']}` is unavailable, returning the results of the
    clusters that are up;
  - make sure the search fails, instead of silently returning partial results, whenever
    `{p['primary']}` is unavailable.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET _resolve/cluster/{FLIGHTS},{p['primary']}:{FLIGHTS},{p['optional']}:{FLIGHTS}

PUT _cluster/settings
{{
  "persistent": {{
    "cluster.remote.{p['optional']}.skip_unavailable": true,
    "cluster.remote.{p['primary']}.skip_unavailable": false
  }}
}}

GET {self.search_path(p)[1:]}
{{ "size": 0 }}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        info = h.send(es, "GET", "/_remote/info")[1] or {}
        c.equal(get(info, f"{p['primary']}.seeds"), [h.TRANSPORT_SEED["b"]], f"{p['primary']} is unchanged")
        c.equal(get(info, f"{p['optional']}.seeds"), [p["dead"]], f"{p['optional']} is unchanged")
        c.equal(get(info, f"{p['optional']}.skip_unavailable"), True, f"{p['optional']} is skipped when unavailable")
        c.equal(get(info, f"{p['primary']}.skip_unavailable"), False, f"{p['primary']} is required")
        status, response = h.send(es, "POST", self.search_path(p) + "?track_total_hits=true", {"size": 0})
        want = h.count(es, FLIGHTS) + h.count(ctx.es_b, FLIGHTS)
        c.check(status == 200 and get(response, "hits.total.value") == want and get(response, "_clusters.skipped") == 1,
                f"the dashboard search succeeds with the local and {p['primary']} results",
                f"HTTP {status}: {str(response)[:200]}")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
