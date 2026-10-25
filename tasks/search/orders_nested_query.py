from lib.sampledata import ALL_CATEGORIES, ECOMMERCE
from lib.tasklib import Task


class OrdersNestedQuery(Task):
    id = "search-orders-nested-query"
    title = "Match conditions on the same array element (nested query)"
    covers = ["search.joining.nested", "search.joining.inner-hits"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        return {"index": f"orders-{iid}", "category": rnd.choice(ALL_CATEGORIES),
                "min_price": rnd.choice([40, 50, 60, 75])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"mappings": {"properties": {
            "order_id": {"type": "keyword"},
            "customer_full_name": {"type": "text"},
            "products": {"type": "nested", "properties": {
                "product_name": {"type": "text"},
                "category": {"type": "keyword"},
                "manufacturer": {"type": "keyword"},
                "price": {"type": "float"},
                "quantity": {"type": "integer"},
            }},
        }}})
        es.post("/_reindex?refresh=true", {
            "source": {"index": ECOMMERCE,
                       "_source": ["order_id", "customer_full_name", "products.product_name", "products.category",
                                   "products.manufacturer", "products.price", "products.quantity"]},
            "dest": {"index": p["index"]},
        }, timeout=120)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds orders with their products as nested objects (look at its
mapping). Find all orders that contain a product which is BOTH in the category
"{p['category']}" (products.category) AND costs more than {p['min_price']} (products.price). Both
conditions must hold for the same product.

Return all of them in one response; there are fewer than 1000. Bonus: also return, with each
order, the products that matched.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {p['index']}/_search
{{
  "size": 1000,
  "query": {{
    "nested": {{
      "path": "products",
      "query": {{
        "bool": {{
          "filter": [
            {{ "term": {{ "products.category": "{p['category']}" }} }},
            {{ "range": {{ "products.price": {{ "gt": {p['min_price']} }} }} }}
          ]
        }}
      }},
      "inner_hits": {{}}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Each condition in its own nested query: may match two different products
        p = ctx.p
        return f"""
GET {p['index']}/_search
{{
  "size": 1000,
  "query": {{
    "bool": {{
      "filter": [
        {{ "nested": {{ "path": "products", "query": {{ "term": {{ "products.category": "{p['category']}" }} }} }} }},
        {{ "nested": {{ "path": "products", "query": {{ "range": {{ "products.price": {{ "gt": {p['min_price']} }} }} }} }} }}
      ]
    }}
  }}
}}
"""
