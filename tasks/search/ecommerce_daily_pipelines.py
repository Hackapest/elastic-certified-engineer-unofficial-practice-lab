from lib.sampledata import ECOMMERCE, ALL_CATEGORIES
from lib.tasklib import Task


class EcommerceDailyPipelines(Task):
    id = "search-ecommerce-daily-pipelines"
    title = "Day-over-day change, moving average and ratios (derivative, moving_fn, bucket_script)"
    covers = ["search.pipeline-aggs.derivative", "search.pipeline-aggs.moving-fn", "search.pipeline-aggs.bucket-script",
              "search.bucket-aggs.date-histogram", "search.metric-aggs.sum"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"category": rnd.choice(ALL_CATEGORIES), "window": rnd.choice([3, 5, 7]),
                "fn": rnd.choice(["average", "maximum", "minimum"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
For orders in `{ECOMMERCE}` containing the category "{p['category']}" (category.keyword), build a
daily report (order_date, calendar days, UTC). Per day:

  revenue      the sum of taxful_total_price
  items        the sum of total_quantity
  per_item     revenue divided by items, computed by Elasticsearch from the two values above
  change       the change in revenue from the previous day
  trend        the {p['fn']} of the revenue of the {p['window']} days BEFORE this day (not including
               this day), computed with a moving function aggregation

No hits, no other aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        fn = {"average": "unweightedAvg", "maximum": "max", "minimum": "min"}[p["fn"]]
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "category.keyword": "{p['category']}" }} }},
  "aggs": {{
    "days": {{
      "date_histogram": {{ "field": "order_date", "calendar_interval": "day" }},
      "aggs": {{
        "revenue": {{ "sum": {{ "field": "taxful_total_price" }} }},
        "items": {{ "sum": {{ "field": "total_quantity" }} }},
        "per_item": {{
          "bucket_script": {{
            "buckets_path": {{ "revenue": "revenue", "items": "items" }},
            "script": "params.revenue / params.items"
          }}
        }},
        "change": {{ "derivative": {{ "buckets_path": "revenue" }} }},
        "trend": {{
          "moving_fn": {{
            "buckets_path": "revenue",
            "window": {p['window']},
            "script": "MovingFunctions.{fn}(values)"
          }}
        }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # A window that includes the current day (shift 1)
        return self.solution(ctx).replace(f'"window": {ctx.p["window"]},', f'"window": {ctx.p["window"]}, "shift": 1,')
