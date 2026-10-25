from lib.sampledata import COLORS, ECOMMERCE, PRODUCT_WORDS
from lib.tasklib import Task


class EcommerceDisMax(Task):
    id = "search-ecommerce-dis-max"
    title = "Best matching clause wins, others add a little (dis_max)"
    covers = ["search.compound.dis-max", "search.fulltext.match"]
    answer = "query"
    compare = "hits_scored"

    def params(self, rnd, iid):
        words = [rnd.choice(COLORS), rnd.choice(PRODUCT_WORDS), rnd.choice(["shoes", "clothing", "accessories"])]
        rnd.shuffle(words)
        return {"text": " ".join(words), "tie": rnd.choice([0.2, 0.3, 0.5, 0.7]), "boost": rnd.choice([2, 3]),
                "top": rnd.choice([10, 15, 20])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{ECOMMERCE}`, search for "{p['text']}" with three separate match queries:

  - on products.product_name, with a boost of {p['boost']}
  - on category
  - on manufacturer

An order's score must be the score of its best matching clause, plus {p['tie']} times the scores
of the other matching clauses (so matching several fields helps, but much less than in a sum).

Return the {p['top']} best-scoring orders, best first.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": {p['top']},
  "query": {{
    "dis_max": {{
      "tie_breaker": {p['tie']},
      "queries": [
        {{ "match": {{ "products.product_name": {{ "query": "{p['text']}", "boost": {p['boost']} }} }} }},
        {{ "match": {{ "category": "{p['text']}" }} }},
        {{ "match": {{ "manufacturer": "{p['text']}" }} }}
      ]
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # No tie breaker: only the best clause counts
        return self.solution(ctx).replace(f'"tie_breaker": {ctx.p["tie"]},', "")
