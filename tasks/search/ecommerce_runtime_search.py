from lib.sampledata import ECOMMERCE
from lib.tasklib import Task


class EcommerceRuntimeSearch(Task):
    id = "search-ecommerce-runtime-search"
    title = "Define a runtime field in the search request and aggregate on it"
    covers = ["ingest.mapping.runtime-search", "search.aggs.aggs-scripts-runtime", "search.bucket-aggs.terms",
              "search.metric-aggs.avg"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        a = rnd.choice([30, 40, 50])
        return {"a": a, "b": a + rnd.choice([40, 60, 80])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{ECOMMERCE}`, without changing the index or its mapping, put every order into a price band
by taxful_total_price, using a field `price_band` that only exists in your search request:

  "budget"    below {p['a']}
  "regular"   from {p['a']} (included) to {p['b']} (excluded)
  "premium"   {p['b']} and above

For each band, return the number of orders and the average total_quantity. No hits, and no
other aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 0,
  "runtime_mappings": {{
    "price_band": {{
      "type": "keyword",
      "script": \"\"\"
        double price = doc['taxful_total_price'].value;
        if (price < {p['a']}) {{ emit('budget'); }}
        else if (price < {p['b']}) {{ emit('regular'); }}
        else {{ emit('premium'); }}
      \"\"\"
    }}
  }},
  "aggs": {{
    "bands": {{
      "terms": {{ "field": "price_band" }},
      "aggs": {{
        "avg_items": {{ "avg": {{ "field": "total_quantity" }} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Upper edge included in "regular"
        p = ctx.p
        return self.solution(ctx).replace(f"price < {p['b']}", f"price <= {p['b'] + 10}")
