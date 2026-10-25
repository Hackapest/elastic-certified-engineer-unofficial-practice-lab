import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task  # noqa: E402


class CcsEsql(Task):
    id = "cluster-ccs-esql"
    title = "ES|QL over a local and a remote index together"
    covers = ["search.ccs.esql-ccs", "search.ccs.multiple"]
    answer = "query"
    compare = "esql"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        return {"alias": f"{rnd.choice(['cluster_b', 'americas', 'us_dc'])}_{iid}", "index": f"sales-{iid}",
                "channel": rnd.choice(h.CHANNELS), "min_qty": rnd.choice([2, 3, 4])}

    def setup(self, ctx):
        h.setup_sales(ctx, ctx.p["index"])
        h.set_remote(ctx.es, ctx.p["alias"], [h.TRANSPORT_SEED["b"]], skip_unavailable=False)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Sales are recorded in an index `{p['index']}` on each cluster: cluster A has the European
stores, cluster B (the remote cluster `{p['alias']}` on cluster A) the North American ones.

From cluster A, write one ES|QL query over both clusters' `{p['index']}` that looks at
{p['channel']} sales with a quantity of at least {p['min_qty']}, and returns per country:

  country   the country
  sales     the number of such sales
  units     the total quantity
  avg_price the average price, rounded to 2 decimals

Return exactly these columns in this order, one row per country, sorted by units from highest
to lowest, then by country. Run it with the _query API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f'''
POST _query
{{
  "query": """
    FROM {p['index']}, {p['alias']}:{p['index']}
    | WHERE channel == "{p['channel']}" AND quantity >= {p['min_qty']}
    | STATS sales = COUNT(*), units = SUM(quantity), avg_price = ROUND(AVG(price), 2) BY country
    | SORT units DESC, country
    | KEEP country, sales, units, avg_price
  """
}}
'''

    def wrong_answer(self, ctx):
        # Only the local index
        return self.solution(ctx).replace(f", {ctx.p['alias']}:{ctx.p['index']}", "")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
