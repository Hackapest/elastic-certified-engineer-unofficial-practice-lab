from lib.sampledata import ECOMMERCE
from lib.tasklib import Task, _bucket_id, _round, get


def deep_canon(obj):
    """Aggregation results without user-chosen names, descending through single-bucket aggregations
    (nested, reverse_nested), whose sub-buckets the shared canonical_aggs doesn't compare."""
    if isinstance(obj, list):
        return sorted(repr(deep_canon(x)) for x in obj)
    scalars = sorted((k, _round(v)) for k, v in obj.items()
                     if (isinstance(v, (int, float)) or v is None) and k != "key")
    kids = sorted(repr(deep_canon(v)) for k, v in obj.items() if isinstance(v, dict) and k != "meta")
    buckets = [(_bucket_id(b), deep_canon(b)) for b in obj.get("buckets", [])]
    return (scalars, kids, buckets)

METRICS = {"average order value": ("avg", "taxful_total_price"), "total revenue": ("sum", "taxful_total_price"),
           "average number of items per order": ("avg", "total_quantity")}


class OrdersNestedAggs(Task):
    id = "search-orders-nested-aggs"
    title = "Aggregate nested products and step back to the orders (nested, reverse_nested)"
    covers = ["search.bucket-aggs.nested", "search.bucket-aggs.reverse-nested", "search.bucket-aggs.terms",
              "search.aggs.sub-aggregations"]
    answer = "query"

    def params(self, rnd, iid):
        return {"index": f"orders-{iid}", "group": rnd.choice(["products.manufacturer", "products.category"]),
                "metric": rnd.choice(sorted(METRICS)), "top": rnd.choice([3, 5, 8])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"mappings": {"properties": {
            "order_id": {"type": "keyword"},
            "taxful_total_price": {"type": "float"},
            "total_quantity": {"type": "integer"},
            "products": {"type": "nested", "properties": {
                "product_name": {"type": "text"},
                "category": {"type": "keyword"},
                "manufacturer": {"type": "keyword"},
                "price": {"type": "float"},
            }},
        }}})
        es.post("/_reindex?refresh=true", {
            "source": {"index": ECOMMERCE,
                       "_source": ["order_id", "taxful_total_price", "total_quantity", "products.product_name",
                                   "products.category", "products.manufacturer", "products.price"]},
            "dest": {"index": p["index"]},
        }, timeout=120)

    def prompt(self, ctx):
        p = ctx.p
        what = p["group"].split(".")[1]
        return f"""
In `{p['index']}`, products are nested objects inside each order (look at the mapping).

For the {p['top']} {what}s ({p['group']}) that appear in the most product lines, return:
  - the number of product lines with that {what}, and their average price (products.price);
  - the number of ORDERS containing at least one such product, and the {p['metric']}
    ({METRICS[p['metric']][1]}, an order-level field) of those orders.

No hits, one request.
"""

    def solution(self, ctx):
        p = ctx.p
        kind, field = METRICS[p["metric"]]
        return f"""
GET {p['index']}/_search
{{
  "size": 0,
  "aggs": {{
    "products": {{
      "nested": {{ "path": "products" }},
      "aggs": {{
        "groups": {{
          "terms": {{ "field": "{p['group']}", "size": {p['top']} }},
          "aggs": {{
            "avg_price": {{ "avg": {{ "field": "products.price" }} }},
            "orders": {{
              "reverse_nested": {{}},
              "aggs": {{
                "metric": {{ "{kind}": {{ "field": "{field}" }} }}
              }}
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""

    def grade(self, ctx, c, answer, reference):
        got, want = get(answer, "aggregations"), get(reference, "aggregations")
        if not c.check(got, "returns the expected aggregation results", "the response has no aggregations"):
            return
        c.check(deep_canon(got) == deep_canon(want), "returns the expected aggregation results",
                "the aggregation results differ from the reference solution "
                "(check the buckets, their order, and the metric values)")

    def wrong_answer(self, ctx):
        # Without reverse_nested the order-level field is invisible from the nested documents
        kind, field = METRICS[ctx.p["metric"]]
        return self.solution(ctx).replace(f'''"orders": {{
              "reverse_nested": {{}},
              "aggs": {{
                "metric": {{ "{kind}": {{ "field": "{field}" }} }}
              }}
            }}''', f'"metric": {{ "{kind}": {{ "field": "{field}" }} }}')
