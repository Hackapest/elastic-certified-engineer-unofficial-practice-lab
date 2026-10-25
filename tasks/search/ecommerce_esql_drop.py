from lib.sampledata import ECOMMERCE, LAST_NAMES
from lib.tasklib import Task


class EcommerceEsqlDrop(Task):
    id = "search-ecommerce-esql-drop"
    title = "Remove columns by pattern in ES|QL (DROP)"
    covers = ["search.esql.command.drop", "search.esql.command.limit", "search.esql.command.sort",
              "search.esql.command.where", "search.esql.command.from"]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        prefixes = rnd.sample(["products", "geoip", "customer_", "event"], 2)
        return {"last": rnd.choice(LAST_NAMES), "limit": rnd.choice([3, 5, 7]), "prefixes": sorted(prefixes)}

    def pattern(self, prefix):
        return f"{prefix}*" if prefix.endswith("_") else f"{prefix}.*"

    def prompt(self, ctx):
        p = ctx.p
        dropped = " and ".join(f'"{self.pattern(x)}"' for x in p["prefixes"])
        return f"""
Write an ES|QL query on `{ECOMMERCE}` that returns the {p['limit']} most recent orders (order_date) of
customers with the last name "{p['last']}" (customer_last_name.keyword).

Return all columns except the ones matching {dropped}, in the default column
order. Run it with the _query API.
"""

    def solution(self, ctx):
        p = ctx.p
        drops = ", ".join(self.pattern(x) for x in p["prefixes"])
        return f'''
POST _query
{{
  "query": """
    FROM {ECOMMERCE}
    | WHERE customer_last_name.keyword == "{p['last']}"
    | SORT order_date DESC
    | LIMIT {p['limit']}
    | DROP {drops}
  """
}}
'''

    def wrong_answer(self, ctx):
        # Drops only the first group of columns
        p = ctx.p
        return self.solution(ctx).replace(f", {self.pattern(p['prefixes'][1])}", "")
