from lib.tasklib import Task

INDEX = "kibana_sample_data_ecommerce"
CATEGORIES = {
    "FEMALE": ["Women's Clothing", "Women's Shoes", "Women's Accessories"],
    "MALE": ["Men's Clothing", "Men's Shoes", "Men's Accessories"],
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class EcommerceBool(Task):
    id = "search-ecommerce-bool"
    title = "Find orders with a bool query of filters"
    covers = [
        "search.compound.bool", "search.basics.query-filter-context", "search.term.term",
        "search.term.range", "search.results.from-size",
    ]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        gender = rnd.choice(sorted(CATEGORIES))
        low = rnd.randrange(30, 95, 5)
        return {
            "gender": gender,
            "category": rnd.choice(CATEGORIES[gender]),
            "low": low,
            "high": low + 15,
            "day": rnd.choice(DAYS),
        }

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{INDEX}`, find all orders where:

  - the customer's gender is {p['gender']}
  - the order contains a product of the category "{p['category']}"
  - the total price including tax (taxful_total_price) is between {p['low']} and {p['high']}, both included
  - the order was not placed on a {p['day']} (day_of_week)

Return all matching orders in one response; there are fewer than 500.
None of the conditions should affect the relevance score.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {INDEX}/_search
{{
  "size": 500,
  "query": {{
    "bool": {{
      "filter": [
        {{ "term": {{ "customer_gender": "{p['gender']}" }} }},
        {{ "term": {{ "category.keyword": "{p['category']}" }} }},
        {{ "range": {{ "taxful_total_price": {{ "gte": {p['low']}, "lte": {p['high']} }} }} }}
      ],
      "must_not": [
        {{ "term": {{ "day_of_week": "{p['day']}" }} }}
      ]
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Forgets the day condition
        return self.solution(ctx).replace('"must_not"', '"should"')

    def grade(self, ctx, c, answer, reference):
        super().grade(ctx, c, answer, reference)
        scores = {h.get("_score") for h in answer.get("hits", {}).get("hits", [])}
        c.check(len(scores) <= 1, "the conditions don't affect the score (filter context)",
                "the hits have different scores; put the conditions in filter or must_not")
