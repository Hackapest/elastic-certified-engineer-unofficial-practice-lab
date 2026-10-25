from lib.sampledata import CONTINENTS, ECOMMERCE
from lib.tasklib import Task


class EcommerceRate(Task):
    id = "search-ecommerce-rate"
    title = "Rates per time unit inside a date histogram (rate aggregation)"
    covers = ["search.metric-aggs.rate", "search.bucket-aggs.date-histogram", "search.aggs.sub-aggregations"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"continent": rnd.choice(CONTINENTS), "bucket": rnd.choice(["week", "month"]),
                "unit": rnd.choice(["day", "hour"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{ECOMMERCE}`, for orders from customers in {p['continent']} (geoip.continent_name), return per
calendar {p['bucket']} (order_date, UTC):

  - the average revenue per {p['unit']} in that {p['bucket']}: the sum of taxful_total_price divided by the
    number of {p['unit']}s in the {p['bucket']}
  - the average number of orders per {p['unit']} in that {p['bucket']}

Use the aggregation made for exactly this. No hits, and no other aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "geoip.continent_name": "{p['continent']}" }} }},
  "aggs": {{
    "per_{p['bucket']}": {{
      "date_histogram": {{ "field": "order_date", "calendar_interval": "{p['bucket']}" }},
      "aggs": {{
        "revenue_per_{p['unit']}": {{ "rate": {{ "field": "taxful_total_price", "unit": "{p['unit']}" }} }},
        "orders_per_{p['unit']}": {{ "rate": {{ "unit": "{p['unit']}" }} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Another time unit
        p = ctx.p
        other = "day" if p["unit"] == "hour" else "hour"
        return self.solution(ctx).replace(f'"unit": "{p["unit"]}"', f'"unit": "{other}"')
