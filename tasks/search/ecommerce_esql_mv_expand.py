from lib.sampledata import ECOMMERCE
from lib.tasklib import Task

MAKERS = ["Low Tide Media", "Elitelligence", "Oceanavigations", "Tigress Enterprises", "Pyramidustries"]


class EcommerceEsqlMvExpand(Task):
    id = "search-ecommerce-esql-mv-expand"
    title = "Multivalued fields in ES|QL (MV_EXPAND, MV_COUNT, MV_MAX, RENAME)"
    covers = ["search.esql.command.mv-expand", "search.esql.functions.multivalue", "search.esql.multivalued",
              "search.esql.command.rename", "search.esql.command.limit",
              "search.esql.functions.operators"]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        return {"lines": rnd.choice([2, 3]), "excluded": rnd.choice(MAKERS), "top": rnd.choice([5, 8, 10]),
                "price": rnd.choice(["highest", "lowest"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{ECOMMERCE}`, an order lists the manufacturers of its products in manufacturer.keyword (a
multivalued field) and the product prices in products.price (also multivalued).

Write an ES|QL query that, for orders with at least {p['lines']} product lines (count the values of
products.product_id), returns one row per manufacturer, leaving out "{p['excluded']}" (an order that
contains it still counts for its other manufacturers), with these columns in this order:

  manufacturer    the manufacturer
  orders          the number of such orders containing that manufacturer
  avg_price       the average, over those orders, of each order's {p['price']} product price,
                  rounded to 2 decimals

Sorted by orders (highest first), then manufacturer (A to Z); only the first {p['top']} rows.
"""

    def solution(self, ctx):
        p = ctx.p
        fn = "MV_MAX" if p["price"] == "highest" else "MV_MIN"
        return f'''
POST _query
{{
  "query": """
    FROM {ECOMMERCE}
    | EVAL lines = MV_COUNT(products.product_id), order_price = {fn}(products.price)
    | WHERE lines >= {p['lines']}
    | MV_EXPAND manufacturer.keyword
    | RENAME manufacturer.keyword AS manufacturer
    | WHERE manufacturer != "{p['excluded']}"
    | STATS orders = COUNT(*), avg_price = ROUND(AVG(order_price), 2) BY manufacturer
    | SORT orders DESC, manufacturer
    | LIMIT {p['top']}
  """
}}
'''

    def wrong_answer(self, ctx):
        # Filtering the multivalued field before expanding it drops whole orders
        p = ctx.p
        fn = "MV_MAX" if p["price"] == "highest" else "MV_MIN"
        return f'''
POST _query
{{
  "query": """
    FROM {ECOMMERCE}
    | EVAL lines = MV_COUNT(products.product_id), order_price = {fn}(products.price)
    | WHERE lines >= {p['lines']} AND manufacturer.keyword != "{p['excluded']}"
    | STATS orders = COUNT(*), avg_price = ROUND(AVG(order_price), 2) BY manufacturer = manufacturer.keyword
    | SORT orders DESC, manufacturer
    | LIMIT {p['top']}
  """
}}
'''
