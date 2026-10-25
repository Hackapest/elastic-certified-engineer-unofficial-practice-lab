import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.sampledata import FLIGHT_CARRIERS, FLIGHTS  # noqa: E402
from lib.tasklib import Task  # noqa: E402

COUNTRIES = {"JP": "Japan", "CN": "China", "CA": "Canada", "AU": "Australia", "GB": "the United Kingdom",
             "IN": "India", "RU": "Russia"}


class CcsSearch(Task):
    id = "cluster-ccs-search"
    title = "Search an index on a remote cluster"
    covers = ["search.ccs.search", "cluster.remote.remote-info"]
    answer = "query"
    compare = "hits"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        return {"alias": f"{rnd.choice(['cluster_b', 'dc_west', 'reporting'])}_{iid}",
                "carrier": rnd.choice(FLIGHT_CARRIERS), "country": rnd.choice(sorted(COUNTRIES))}

    def setup(self, ctx):
        h.set_remote(ctx.es, ctx.p["alias"], [h.TRANSPORT_SEED["b"]], skip_unavailable=False)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster B is configured on cluster A as the remote cluster `{p['alias']}` (see GET _remote/info).
Cluster A also has its own copy of `{FLIGHTS}`, but this report must come from cluster B.

From cluster A, write a search that returns all cancelled {p['carrier']} flights that departed
from {COUNTRIES[p['country']]} (OriginCountry "{p['country']}") in cluster B's `{FLIGHTS}`
index, and nothing from cluster A's. Return all matching flights (there are fewer than 100).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {p['alias']}:{FLIGHTS}/_search
{{
  "size": 100,
  "query": {{
    "bool": {{
      "filter": [
        {{ "term": {{ "Cancelled": true }} }},
        {{ "term": {{ "Carrier": "{p['carrier']}" }} }},
        {{ "term": {{ "OriginCountry": "{p['country']}" }} }}
      ]
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Searches the local copy instead of cluster B's
        return self.solution(ctx).replace(f"GET {ctx.p['alias']}:", "GET ")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
