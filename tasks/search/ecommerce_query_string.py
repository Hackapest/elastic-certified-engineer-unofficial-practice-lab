from lib.sampledata import COLORS, ECOMMERCE
from lib.tasklib import Task

# Product words with a few hundred orders each, so OR-ing two of them stays below 1000 orders
WORDS = ["coat", "trainers", "jacket", "bag", "dress", "jumper"]
MANUFACTURERS = ["Low Tide Media", "Elitelligence", "Oceanavigations", "Tigress Enterprises"]


class EcommerceQueryString(Task):
    id = "search-ecommerce-query-string"
    title = "Search with Lucene syntax (query_string)"
    covers = ["search.fulltext.query-string", "search.basics.search-api"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        w1, w2 = rnd.sample(WORDS, 2)
        return {"color": rnd.choice(COLORS[1:]), "w1": w1, "w2": w2, "manufacturer": rnd.choice(MANUFACTURERS)}

    def query(self, p):
        return (f'products.product_name:(({p["color"]} AND {p["w1"]}) OR {p["w2"]}) '
                f'AND NOT manufacturer.keyword:\\"{p["manufacturer"]}\\"')

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The support team searches `{ECOMMERCE}` with a search box that accepts Lucene query syntax, and
wants you to write the query they would type. Using a single query_string query, find the orders
where:

  - a product name (products.product_name) contains both the words "{p['color']}" and "{p['w1']}",
    OR a product name contains the word "{p['w2']}";
  - AND the order's manufacturer is not exactly "{p['manufacturer']}" (manufacturer.keyword).

Return all matching orders in one response (there are fewer than 1000).
"""

    def solution(self, ctx):
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 1000,
  "query": {{
    "query_string": {{
      "query": "{self.query(ctx.p)}"
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Forgets the manufacturer exclusion: the big manufacturers make many of these products
        p = ctx.p
        return self.solution(ctx).replace(f' AND NOT manufacturer.keyword:\\"{p["manufacturer"]}\\"', "")
