from lib.sampledata import CONTINENTS, ECOMMERCE
from lib.tasklib import Task


class EcommerceTopHits(Task):
    id = "search-ecommerce-top-hits"
    title = "Unique counts and the top document per bucket (cardinality, top_hits)"
    covers = ["search.metric-aggs.cardinality", "search.metric-aggs.top-hits", "search.bucket-aggs.terms",
              "search.aggs.sub-aggregations", "search.aggs.aggs-with-query"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"continent": rnd.choice(CONTINENTS), "top": rnd.choice([1, 2, 3])}

    def prompt(self, ctx):
        p = ctx.p
        orders = "order" if p["top"] == 1 else f"{p['top']} orders"
        return f"""
In `{ECOMMERCE}`, for orders from customers in {p['continent']} (geoip.continent_name), return for
every category (category.keyword):

  - the number of different customers who ordered in that category (customer_id)
  - the most expensive {orders} in that category (by taxful_total_price), as documents

Categories sorted by number of orders, most first. No other hits, and no other aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 0,
  "query": {{
    "term": {{ "geoip.continent_name": "{p['continent']}" }}
  }},
  "aggs": {{
    "categories": {{
      "terms": {{ "field": "category.keyword" }},
      "aggs": {{
        "customers": {{ "cardinality": {{ "field": "customer_id" }} }},
        "most_expensive": {{
          "top_hits": {{
            "size": {p['top']},
            "sort": [{{ "taxful_total_price": "desc" }}]
          }}
        }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Cheapest instead of most expensive
        return self.solution(ctx).replace('"taxful_total_price": "desc"', '"taxful_total_price": "asc"')
