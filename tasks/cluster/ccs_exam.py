import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task  # noqa: E402


class CcsExam(Task):
    id = "cluster-ccs-exam"
    title = "Exam-style: connect a remote cluster and aggregate over local and remote data"
    covers = ["cluster.remote.cert-model", "cluster.remote.settings", "search.ccs.search", "search.ccs.multiple",
              "search.ccs.options"]
    size = "exam"
    answer = "query"
    compare = "aggs"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        return {"alias": f"{rnd.choice(['americas', 'cluster_b', 'na_sales'])}_{iid}", "index": f"sales-{iid}",
                "category": rnd.choice(h.CATEGORIES), "from_day": rnd.choice([5, 8, 10]),
                "to_day": rnd.choice([20, 22, 25]), "seed": rnd.choice(["es-b1:9300", "es-b2:9300"])}

    def setup(self, ctx):
        h.setup_sales(ctx, ctx.p["index"])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Sales are recorded in an index `{p['index']}` on each cluster: cluster A has the European
stores, cluster B the North American ones. Management wants one report over both.

  1. On cluster A, add cluster B as the persistent remote cluster `{p['alias']}`, using the
     certificate-based security model in sniff mode with the seed {p['seed']} (cluster B's
     transport port). Searches that include it must fail if it is unreachable, rather than
     returning partial results.
  2. From cluster A, write one search over both clusters' `{p['index']}` that considers only
     "{p['category']}" sales from 2026-09-{p['from_day']:02d} (inclusive) to 2026-09-{p['to_day']:02d}
     (exclusive), returns no documents, and aggregates:
       - per country (all countries): the total quantity sold, and the highest price
       - over everything: the average price

Hand in the search (you may include the settings request before it; the response of the last
request is graded).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _cluster/settings
{{
  "persistent": {{
    "cluster.remote.{p['alias']}.mode": "sniff",
    "cluster.remote.{p['alias']}.seeds": ["{p['seed']}"],
    "cluster.remote.{p['alias']}.skip_unavailable": false
  }}
}}

GET {p['index']},{p['alias']}:{p['index']}/_search
{{
  "size": 0,
  "query": {{
    "bool": {{
      "filter": [
        {{ "term": {{ "category": "{p['category']}" }} }},
        {{ "range": {{ "@timestamp": {{ "gte": "2026-09-{p['from_day']:02d}", "lt": "2026-09-{p['to_day']:02d}" }} }} }}
      ]
    }}
  }},
  "aggs": {{
    "by_country": {{
      "terms": {{ "field": "country", "size": 20 }},
      "aggs": {{
        "units": {{ "sum": {{ "field": "quantity" }} }},
        "top_price": {{ "max": {{ "field": "price" }} }}
      }}
    }},
    "avg_price": {{ "avg": {{ "field": "price" }} }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Only the local cluster
        return self.solution(ctx).replace(f",{ctx.p['alias']}:{ctx.p['index']}/_search", "/_search")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
