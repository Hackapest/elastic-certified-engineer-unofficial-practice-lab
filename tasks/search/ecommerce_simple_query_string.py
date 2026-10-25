from lib.sampledata import ECOMMERCE
from lib.tasklib import Task

COLORS = ["white", "blue", "grey", "red", "cognac"]
PAIRS = [("boots", "trainers"), ("dress", "skirt"), ("jacket", "coat"), ("jumper", "cardigan"),
         ("bag", "rucksack"), ("shirt", "blouse")]


class EcommerceSimpleQueryString(Task):
    id = "search-ecommerce-simple-query-string"
    title = "A forgiving search box (simple_query_string)"
    covers = ["search.fulltext.simple-query-string"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        a, b = rnd.choice(PAIRS)
        must, excluded = rnd.sample(COLORS, 2)
        return {"a": a, "b": b, "must": must, "excluded": excluded}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
A search box on the shop's back office must never fail on bad syntax, so it uses the
simple_query_string query. Write the request for this search on `{ECOMMERCE}`, searching the fields
products.product_name and category:

  the text must contain "{p['must']}", AND either "{p['a']}" or "{p['b']}", AND must NOT contain "{p['excluded']}"

Write the query text with the simple_query_string operators (+, |, -, parentheses) and make sure
the exclusion really excludes. Return all matching orders in one response (fewer than 1000).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 1000,
  "query": {{
    "simple_query_string": {{
      "query": "{p['must']} ({p['a']} | {p['b']}) -{p['excluded']}",
      "fields": ["products.product_name", "category"],
      "default_operator": "and"
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # With the default operator (or), "-x" means "or not x" and matches almost everything
        return self.solution(ctx).replace('"default_operator": "and"', '"default_operator": "or"')
