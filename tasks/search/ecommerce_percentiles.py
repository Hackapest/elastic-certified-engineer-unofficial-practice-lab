from lib.sampledata import ECOMMERCE
from lib.tasklib import Task

PERCENTS = [[50, 95], [25, 75], [10, 90], [50, 99], [75, 95]]


class EcommercePercentiles(Task):
    id = "search-ecommerce-percentiles"
    title = "Distribution of order values (percentiles, percentile_ranks, extended_stats)"
    covers = ["search.metric-aggs.percentiles", "search.metric-aggs.percentile-ranks",
              "search.metric-aggs.extended-stats", "search.bucket-aggs.terms", "search.aggs.sub-aggregations"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"percents": rnd.choice(PERCENTS), "rank_value": rnd.choice([50, 75, 100, 150]),
                "sigma": rnd.choice([1, 2, 3]), "gender": rnd.choice(["MALE", "FEMALE"])}

    def prompt(self, ctx):
        p = ctx.p
        pc = " and ".join(str(x) for x in p["percents"])
        return f"""
For orders in `{ECOMMERCE}` placed by customers of gender {p['gender']} (customer_gender), compute
per category (category.keyword, all of them, ordered by number of orders, most first):

  - the {pc}th percentiles of taxful_total_price;
  - the percentage of orders whose taxful_total_price is at or below {p['rank_value']};
  - extended statistics of taxful_total_price, with standard deviation bounds at {p['sigma']}
    standard deviations.

No hits, no other aggregations. Keep the default (keyed) response format of the
percentile aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "customer_gender": "{p['gender']}" }} }},
  "aggs": {{
    "categories": {{
      "terms": {{ "field": "category.keyword" }},
      "aggs": {{
        "price_percentiles": {{ "percentiles": {{ "field": "taxful_total_price", "percents": {p['percents']} }} }},
        "share_below": {{ "percentile_ranks": {{ "field": "taxful_total_price", "values": [{p['rank_value']}] }} }},
        "price_stats": {{ "extended_stats": {{ "field": "taxful_total_price", "sigma": {p['sigma']} }} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Default sigma (2) or 3 instead of what was asked
        sigma = ctx.p["sigma"]
        return self.solution(ctx).replace(f'"sigma": {sigma}', f'"sigma": {3 if sigma != 3 else 1}')
