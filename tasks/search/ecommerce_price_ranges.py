from lib.sampledata import ECOMMERCE
from lib.tasklib import Task


class EcommercePriceRanges(Task):
    id = "search-ecommerce-price-ranges"
    title = "Price bands with statistics (range, stats, filters)"
    covers = ["search.bucket-aggs.range", "search.metric-aggs.stats", "search.bucket-aggs.filters",
              "search.aggs.sub-aggregations"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        a = rnd.choice([25, 30, 40])
        b = a + rnd.choice([30, 40, 50])
        return {"a": a, "b": b, "metric": rnd.choice(["total_quantity", "total_unique_products"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{ECOMMERCE}`, split all orders into three price bands by taxful_total_price:

  cheap       below {p['a']}
  medium      from {p['a']} (included) to {p['b']} (excluded)
  expensive   {p['b']} and above

For each band, return the statistics (count, min, max, avg, sum) of {p['metric']}, and, within
the band, the number of orders from MALE and from FEMALE customers (customer_gender) as two
buckets named "male" and "female". Keep the bands in the order above. No hits, and no other
aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 0,
  "aggs": {{
    "price_bands": {{
      "range": {{
        "field": "taxful_total_price",
        "ranges": [
          {{ "key": "cheap", "to": {p['a']} }},
          {{ "key": "medium", "from": {p['a']}, "to": {p['b']} }},
          {{ "key": "expensive", "from": {p['b']} }}
        ]
      }},
      "aggs": {{
        "{p['metric']}_stats": {{ "stats": {{ "field": "{p['metric']}" }} }},
        "by_gender": {{
          "filters": {{
            "filters": {{
              "male": {{ "term": {{ "customer_gender": "MALE" }} }},
              "female": {{ "term": {{ "customer_gender": "FEMALE" }} }}
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Off-by-one band edge
        p = ctx.p
        return self.solution(ctx).replace(f'"from": {p["b"]} }}', f'"from": {p["b"] + 5} }}').replace(
            f'"to": {p["b"]} }}', f'"to": {p["b"] + 5} }}')
