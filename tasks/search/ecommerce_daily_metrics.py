from lib.sampledata import ECOMMERCE, ALL_CATEGORIES
from lib.tasklib import Task


class EcommerceDailyMetrics(Task):
    id = "search-ecommerce-daily-metrics"
    title = "Weekday metrics (value_count, min, weighted_avg)"
    covers = ["search.metric-aggs.value-count", "search.metric-aggs.min", "search.metric-aggs.weighted-avg",
              "search.bucket-aggs.terms", "search.aggs.sub-aggregations"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"category": rnd.choice(ALL_CATEGORIES), "min_field": rnd.choice(["taxful_total_price", "total_quantity"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
For orders in `{ECOMMERCE}` that contain the category "{p['category']}" (category.keyword), compute
per weekday (day_of_week; all 7 days, ordered by number of orders, most first):

  products_sold   the number of product lines sold: the number of values of products.product_id
                  (an order with 3 products counts 3)
  smallest        the minimum {p['min_field']}
  weighted_value  the average taxful_total_price, weighted by total_quantity: an order of
                  4 items counts 4 times as much as an order of 1 item

No hits, no other aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "category.keyword": "{p['category']}" }} }},
  "aggs": {{
    "days": {{
      "terms": {{ "field": "day_of_week" }},
      "aggs": {{
        "products_sold": {{ "value_count": {{ "field": "products.product_id" }} }},
        "smallest": {{ "min": {{ "field": "{p['min_field']}" }} }},
        "weighted_value": {{
          "weighted_avg": {{
            "value": {{ "field": "taxful_total_price" }},
            "weight": {{ "field": "total_quantity" }}
          }}
        }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # A plain average, not weighted by quantity
        return self.solution(ctx).replace(
            '''"weighted_avg": {
            "value": { "field": "taxful_total_price" },
            "weight": { "field": "total_quantity" }
          }''', '"avg": { "field": "taxful_total_price" }')
