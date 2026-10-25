from lib.sampledata import COLORS, ECOMMERCE, PRODUCT_WORDS
from lib.tasklib import Task


class EcommerceMultiMatch(Task):
    id = "search-ecommerce-multi-match"
    title = "Search several fields with weights (multi_match)"
    covers = ["search.fulltext.multi-match", "search.fulltext.multi-match-types", "search.fulltext.match"]
    answer = "query"
    compare = "hits_scored"

    def params(self, rnd, iid):
        # A category word too, so several fields match and summing differs from taking the best
        words = [rnd.choice(COLORS), rnd.choice(PRODUCT_WORDS), rnd.choice(["shoes", "clothing", "accessories"])]
        rnd.shuffle(words)
        return {"text": " ".join(words), "boost": rnd.choice([2, 3, 4]), "top": rnd.choice([10, 15, 20])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{ECOMMERCE}`, search for "{p['text']}" in these fields:

  products.product_name, category, manufacturer

The score of an order is the sum of the scores of every field that matches, and a match in
products.product_name counts {p['boost']} times as much as a match in the other fields.

Return the {p['top']} best-scoring orders, best first.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": {p['top']},
  "query": {{
    "multi_match": {{
      "query": "{p['text']}",
      "type": "most_fields",
      "fields": ["products.product_name^{p['boost']}", "category", "manufacturer"]
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # best_fields takes the best field's score instead of the sum
        return self.solution(ctx).replace('"most_fields"', '"best_fields"')
