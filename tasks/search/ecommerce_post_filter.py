from lib.sampledata import ECOMMERCE, ECOMMERCE_CATEGORIES
from lib.tasklib import Task, same_aggs, same_hits

# Manufacturers with at least 25 orders on every weekday for that gender
MAKERS = {"MALE": ["Low Tide Media", "Elitelligence", "Oceanavigations"],
          "FEMALE": ["Tigress Enterprises", "Pyramidustries", "Oceanavigations", "Low Tide Media"]}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class EcommercePostFilter(Task):
    id = "search-ecommerce-post-filter"
    title = "Filter the hits but not the facets (post_filter)"
    covers = ["search.results.post-filter", "search.bucket-aggs.terms", "search.aggs.aggs-with-query"]
    answer = "query"

    def params(self, rnd, iid):
        gender = rnd.choice(sorted(ECOMMERCE_CATEGORIES))
        return {"gender": gender, "manufacturer": rnd.choice(MAKERS[gender]),
                "day": rnd.choice(DAYS)}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
A shop page shows orders from `{ECOMMERCE}` placed on a {p['day']} (day_of_week) by customers of
gender {p['gender']} (customer_gender). On the left it shows a facet: the number of these orders per
manufacturer (manufacturer.keyword, all manufacturers, there are fewer than 30).

The user has clicked the manufacturer "{p['manufacturer']}" in the facet. Now:
  - the hits must only be that manufacturer's orders (of that day and gender): return all of
    them in one response (fewer than 1000);
  - the facet must still show the counts for ALL manufacturers (of that day and gender), so the
    user can switch.

One request. The facet is the only aggregation.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 1000,
  "query": {{
    "bool": {{
      "filter": [
        {{ "term": {{ "day_of_week": "{p['day']}" }} }},
        {{ "term": {{ "customer_gender": "{p['gender']}" }} }}
      ]
    }}
  }},
  "aggs": {{
    "manufacturers": {{ "terms": {{ "field": "manufacturer.keyword", "size": 30 }} }}
  }},
  "post_filter": {{ "term": {{ "manufacturer.keyword": "{p['manufacturer']}" }} }}
}}
"""

    def grade(self, ctx, c, answer, reference):
        same_hits(c, answer, reference, ordered=False)
        same_aggs(c, answer, reference)

    def wrong_answer(self, ctx):
        # The manufacturer in the query: the facet now only shows that manufacturer
        p = ctx.p
        return self.solution(ctx).replace(
            '"filter": [', f'"filter": [ {{ "term": {{ "manufacturer.keyword": "{p["manufacturer"]}" }} }},')
