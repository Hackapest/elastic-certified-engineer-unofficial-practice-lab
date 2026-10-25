from lib.sampledata import ALL_CATEGORIES, ECOMMERCE
from lib.tasklib import Task


class EcommerceHistogram(Task):
    id = "search-ecommerce-histogram"
    title = "Fixed-width numeric buckets (histogram with empty buckets and bounds)"
    covers = ["search.bucket-aggs.histogram", "search.metric-aggs.avg", "search.aggs.sub-aggregations"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        interval = rnd.choice([10, 20, 25, 50])
        return {"interval": interval, "max": rnd.choice([300, 400, 500]), "category": rnd.choice(ALL_CATEGORIES),
                "metric_field": rnd.choice(["total_quantity", "total_unique_products"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
For orders in `{ECOMMERCE}` containing the category "{p['category']}" (category.keyword), build a
price histogram of taxful_total_price with buckets {p['interval']} wide (0-{p['interval']}, {p['interval']}-{2 * p['interval']}, ...).

  - Show every bucket from the one starting at 0 up to and including the one starting at
    {p['max']} ({p['max']}-{p['max'] + p['interval']}), including empty buckets (0 orders).
  - No buckets beyond that last one: orders priced at {p['max'] + p['interval']} or more are left out.
  - For each bucket, the average {p['metric_field']}.

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
    "prices": {{
      "histogram": {{
        "field": "taxful_total_price",
        "interval": {p['interval']},
        "min_doc_count": 0,
        "extended_bounds": {{ "min": 0, "max": {p['max']} }},
        "hard_bounds": {{ "min": 0, "max": {p['max']} }}
      }},
      "aggs": {{
        "avg_metric": {{ "avg": {{ "field": "{p['metric_field']}" }} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # No bounds: empty buckets at the start and end missing, expensive orders included
        return self.solution(ctx).replace(f''',
        "extended_bounds": {{ "min": 0, "max": {ctx.p['max']} }},
        "hard_bounds": {{ "min": 0, "max": {ctx.p['max']} }}''', "")
