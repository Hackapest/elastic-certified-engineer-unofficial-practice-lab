from lib.sampledata import COLORS, ECOMMERCE, PRODUCT_WORDS
from lib.tasklib import Task, get, same_esql


class EcommerceEsqlMatchAsync(Task):
    id = "search-ecommerce-esql-match-async"
    title = "Full-text search with scores in ES|QL, run asynchronously (MATCH, METADATA _score, async)"
    covers = ["search.esql.functions.search", "search.esql.search-tutorial", "search.esql.async",
              "search.esql.command.from", "search.esql.command.sort", "search.esql.command.keep"]
    answer = "query"

    def params(self, rnd, iid):
        return {"text": f"{rnd.choice(COLORS)} {rnd.choice(PRODUCT_WORDS)}", "max_total": rnd.choice([50, 80, 120]),
                "top": rnd.choice([5, 10, 15]), "operator": rnd.choice(["all", "any"])}

    def query(self, p):
        options = ', {"operator": "AND"}' if p["operator"] == "all" else ""
        return f"""
    FROM {ECOMMERCE} METADATA _score
    | WHERE MATCH(products.product_name, "{p['text']}"{options}) AND taxful_total_price <= {p['max_total']}
    | SORT _score DESC, order_id
    | KEEP order_id, taxful_total_price, _score
    | LIMIT {p['top']}
  """

    def prompt(self, ctx):
        p = ctx.p
        words = "ALL of the words" if p["operator"] == "all" else "ANY of the words"
        return f"""
Write an ES|QL full-text search on `{ECOMMERCE}`: orders whose product names (products.product_name)
match {words} "{p['text']}" (a full-text match, scored as relevance), and whose taxful_total_price
is at most {p['max_total']}.

Columns in this order: order_id, taxful_total_price, _score (the relevance score). Sorted by score
(best first), then order_id; only the first {p['top']} rows.

Run it as an ASYNC ES|QL query whose results are kept even if it completes quickly, then fetch the
results with a second request using its ID. Hand in both requests; the second (the fetch) is graded.
"""

    def solution(self, ctx):
        return f'''
POST _query/async
{{
  "query": """{self.query(ctx.p)}""",
  "wait_for_completion_timeout": "30s",
  "keep_on_completion": true
}}

# then, with the "id" from the response:
# GET _query/async/<id>
'''

    def grade(self, ctx, c, answer, reference):
        if reference.get("id"):
            ctx.es.send("DELETE", f"/_query/async/{reference['id']}")   # don't keep the reference's results
        if not c.check(isinstance(answer, dict) and "is_running" in answer, "the answer is an async ES|QL response",
                       "the graded (last) request should be GET _query/async/<id>"):
            return
        if not c.check(not answer.get("is_running"), "the query has finished", "fetch it again a little later"):
            return
        same_esql(c, answer, reference)

    def wrong_answer(self, ctx):
        # A synchronous query: right rows, but not an async response; and sorted ascending
        return f'''
POST _query
{{ "query": """{self.query(ctx.p).replace("_score DESC", "_score ASC")}""" }}
'''
