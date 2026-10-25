from lib.sampledata import ECOMMERCE, PRODUCT_PHRASES
from lib.tasklib import Task


class EcommercePhraseSlop(Task):
    id = "search-ecommerce-phrase-slop"
    title = "Phrase search with words in between (slop)"
    covers = ["search.fulltext.match-phrase", "search.fulltext.match"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        first, last, between = rnd.choice(PRODUCT_PHRASES)
        return {"first": first, "last": last, "between": between}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{ECOMMERCE}`, find all orders that contain a product whose name (products.product_name)
has the word "{p['first']}" followed by the word "{p['last']}", with at most {p['between']} other word(s)
in between. Example: in "Lace-up boots - black", "lace" is followed by "black" with 2 words
("up", "boots") in between.

Return all matching orders in one response; there are fewer than 500.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 500,
  "query": {{
    "match_phrase": {{
      "products.product_name": {{
        "query": "{p['first']} {p['last']}",
        "slop": {p['between']}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Without slop the words must be adjacent
        return self.solution(ctx).replace(f'"slop": {ctx.p["between"]}', '"slop": 0')
