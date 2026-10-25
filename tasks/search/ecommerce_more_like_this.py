from lib.sampledata import ECOMMERCE
from lib.tasklib import Task, get

PRODUCTS = ["Ankle boots - black", "Print T-shirt - black", "Lace-up boots - resin coffee", "Jersey dress - black",
            "Across body bag - black", "Tracksuit top - black", "High-top trainers - black", "Summer dress - black",
            "Bomber Jacket - black", "Classic coat - black"]


class EcommerceMoreLikeThis(Task):
    id = "search-ecommerce-more-like-this"
    title = "Find similar documents (more_like_this)"
    covers = ["search.specialized.more-like-this"]
    answer = "query"
    compare = "hits_scored"

    def params(self, rnd, iid):
        return {"product": rnd.choice(PRODUCTS), "max_terms": rnd.choice([5, 10, 25]), "min_doc_freq": rnd.choice([2, 5]),
                "top": rnd.choice([10, 20])}

    def order_id(self, ctx):
        """The _id of a fixed order containing the product (document IDs differ per install)."""
        r = ctx.es.post(f"/{ECOMMERCE}/_search", {"size": 1, "sort": [{"order_id": "asc"}], "_source": False,
                                                  "query": {"term": {"products.product_name.keyword": ctx.p["product"]}}})
        return get(r, "hits.hits.0._id")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
A "customers also bought" widget shows orders similar to the order with the document ID
`{self.order_id(ctx)}` in `{ECOMMERCE}` (look at it first: it contains "{p['product']}").

Using a more_like_this query that refers to that document (don't copy its text), find orders whose
product names (products.product_name) are similar, with these settings:
  - terms count even if they occur only once in the document;
  - terms must occur in at least {p['min_doc_freq']} documents;
  - use at most {p['max_terms']} query terms.
The order itself must not be in the results. Return the {p['top']} most similar orders, best first.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": {p['top']},
  "query": {{
    "more_like_this": {{
      "fields": ["products.product_name"],
      "like": [ {{ "_index": "{ECOMMERCE}", "_id": "{self.order_id(ctx)}" }} ],
      "min_term_freq": 1,
      "min_doc_freq": {p['min_doc_freq']},
      "max_query_terms": {p['max_terms']}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Includes the order itself
        return self.solution(ctx).replace('"min_term_freq": 1,', '"min_term_freq": 1, "include": true,')
