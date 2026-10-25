from lib.sampledata import ECOMMERCE
from lib.tasklib import Task

# What the user has typed so far: the last word is incomplete
PHRASES = ["ankle bo", "lace-up bo", "print t-sh", "summer dr", "jersey dre", "across body b",
           "tracksuit to", "high-top tra", "classic co", "bomber jac", "long sleeved t", "weekend b"]
ANY_ORDER = ["black ank", "cognac boo", "white tra", "blue jum", "grey sweat", "black bomb", "brown lace",
             "white shi", "black jersey dr"]


class EcommerceSearchAsYouType(Task):
    id = "search-ecommerce-search-as-you-type"
    title = "Match what the user is still typing (match_phrase_prefix, match_bool_prefix)"
    covers = ["search.fulltext.match-phrase-prefix", "search.fulltext.match-bool-prefix"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        kind = rnd.choice(["phrase", "any_order"])
        return {"kind": kind, "text": rnd.choice(PHRASES if kind == "phrase" else ANY_ORDER)}

    def prompt(self, ctx):
        p = ctx.p
        if p["kind"] == "phrase":
            rule = f"""contain the words typed so far as a phrase, in this order and next to each other,
where the last word may be incomplete (so "{p['text']}" matches a name containing
"{p['text']}" followed by more letters of that last word)"""
        else:
            rule = f"""contain ALL the words typed so far, in any order and position, where the last
word may be incomplete (it matches any word starting with it)"""
        return f"""
An autocomplete box searches product names in `{ECOMMERCE}`. The user has typed:

  "{p['text']}"

Find the orders where a product name (products.product_name) must {rule}.

Use a full-text query made for this (no wildcard or regexp queries). Return all matching orders in
one response (fewer than 1000).
"""

    def solution(self, ctx):
        p = ctx.p
        if p["kind"] == "phrase":
            query = f'"match_phrase_prefix": {{ "products.product_name": "{p["text"]}" }}'
        else:
            query = (f'"match_bool_prefix": {{ "products.product_name": '
                     f'{{ "query": "{p["text"]}", "operator": "and" }} }}')
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 1000,
  "query": {{
    {query}
  }}
}}
"""

    def wrong_answer(self, ctx):
        p = ctx.p
        if p["kind"] == "phrase":   # a plain match: any of the words, and no prefix
            return self.solution(ctx).replace("match_phrase_prefix", "match")
        return self.solution(ctx).replace('"operator": "and"', '"operator": "or"')   # any of the words
