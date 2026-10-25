from lib.sampledata import ECOMMERCE, MANUFACTURERS, PRODUCT_WORDS
from lib.tasklib import Task, get, same_hits, same_scores


class EcommerceBoosting(Task):
    id = "search-ecommerce-boosting"
    title = "Demote some results without excluding them (boosting)"
    covers = ["search.compound.boosting", "search.fulltext.match"]
    answer = "query"

    def params(self, rnd, iid):
        return {"word": rnd.choice(PRODUCT_WORDS), "manufacturer": rnd.choice(MANUFACTURERS[:5]),
                "factor": rnd.choice([0.2, 0.3, 0.5]), "top": rnd.choice([10, 20])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{ECOMMERCE}`, search for orders with "{p['word']}" in the product name (products.product_name).
Orders that include products by "{p['manufacturer']}" (manufacturer.keyword) must still be found,
but their score must be multiplied by {p['factor']}, so they rank lower.

Return the {p['top']} best-scoring orders, best first. (The total number of hits must include
the demoted orders.)
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": {p['top']},
  "query": {{
    "boosting": {{
      "positive": {{
        "match": {{ "products.product_name": "{p['word']}" }}
      }},
      "negative": {{
        "term": {{ "manufacturer.keyword": "{p['manufacturer']}" }}
      }},
      "negative_boost": {p['factor']}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Excluding them instead of demoting
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": {p['top']},
  "query": {{
    "bool": {{
      "must": {{ "match": {{ "products.product_name": "{p['word']}" }} }},
      "must_not": {{ "term": {{ "manufacturer.keyword": "{p['manufacturer']}" }} }}
    }}
  }}
}}
"""

    def grade(self, ctx, c, answer, reference):
        same_hits(c, answer, reference, ordered=True)
        same_scores(c, answer, reference)
        c.equal(get(answer, "hits.total.value"), get(reference, "hits.total.value"),
                "demoted orders are still found (total hits)")
