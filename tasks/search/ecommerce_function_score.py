from lib.sampledata import COLORS, ECOMMERCE, PRODUCT_WORDS
from lib.tasklib import Task

MODIFIERS = {"log1p": "log10(1 + total_quantity)", "sqrt": "the square root of total_quantity",
             "none": "total_quantity itself"}


class EcommerceFunctionScore(Task):
    id = "search-ecommerce-function-score"
    title = "Combine relevance with a numeric field (function_score)"
    covers = ["search.compound.function-score", "search.fulltext.match"]
    answer = "query"
    compare = "hits_scored"

    def params(self, rnd, iid):
        return {"text": f"{rnd.choice(COLORS)} {rnd.choice(PRODUCT_WORDS)}", "modifier": rnd.choice(sorted(MODIFIERS)),
                "factor": rnd.choice([1, 2]), "top": rnd.choice([10, 15])}

    def prompt(self, ctx):
        p = ctx.p
        factor = f"{p['factor']} x " if p["factor"] != 1 else ""
        value = MODIFIERS[p["modifier"]]
        if p["factor"] != 1 and p["modifier"] != "none":
            value = MODIFIERS[p["modifier"]].replace("total_quantity", f"{p['factor']} x total_quantity")
            factor = ""
        return f"""
In `{ECOMMERCE}`, search for "{p['text']}" in the product name (products.product_name).
Orders with more items should rank higher: the final score of each order is its relevance
score multiplied by {factor}{value}.

Return the {p['top']} best-scoring orders, best first.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": {p['top']},
  "query": {{
    "function_score": {{
      "query": {{
        "match": {{ "products.product_name": "{p['text']}" }}
      }},
      "field_value_factor": {{
        "field": "total_quantity",
        "factor": {p['factor']},
        "modifier": "{p['modifier']}"
      }},
      "boost_mode": "multiply"
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # The wrong modifier
        modifier = ctx.p["modifier"]
        other = "none" if modifier != "none" else "log1p"
        return self.solution(ctx).replace(f'"modifier": "{modifier}"', f'"modifier": "{other}"')
