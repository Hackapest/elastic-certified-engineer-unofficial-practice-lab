import time

from lib.sampledata import LOG_PRODUCTS, LOGS
from lib.tasklib import Task, get


class LogsAsyncNoWait(Task):
    id = "search-logs-async-no-wait"
    title = "Submit an async search that returns at once, then fetch its results"
    covers = ["search.async.submit", "search.async.get-status-delete", "search.fulltext.match"]
    answer = "query"

    def params(self, rnd, iid):
        return {"product": rnd.choice(LOG_PRODUCTS), "size": rnd.choice([5, 10])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Search `{LOGS}` for log entries that mention "{p['product']}" in the request field (a full-text match),
returning {p['size']} hits, as an asynchronous search:

  - The submit request must return immediately, without waiting even a moment for results.
  - Then fetch the results with a second request, using the ID from the first response.

Hand in both requests; the second one (the fetch) is graded. Check that the search has finished
before you hand it in.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST {LOGS}/_async_search?wait_for_completion_timeout=0
{{
  "size": {p['size']},
  "query": {{ "match": {{ "request": "{p['product']}" }} }}
}}

# then, with the "id" from the response:
# GET _async_search/<id>
"""

    def wrong_answer(self, ctx):
        # A normal, synchronous search
        return self.solution(ctx).replace("/_async_search?wait_for_completion_timeout=0", "/_search")

    def grade(self, ctx, c, answer, reference):
        p, es = ctx.p, ctx.es
        search_id = answer.get("id") if isinstance(answer, dict) else None
        if not c.check(search_id, "the answer is a stored async search",
                       "no search ID: with the default wait, a fast search isn't stored, so use "
                       "wait_for_completion_timeout=0 and hand in the GET _async_search/<id> request"):
            return
        result = {}
        for _ in range(20):
            result = es.send("GET", f"/_async_search/{search_id}")[1] or {}
            if not result.get("is_running"):
                break
            time.sleep(0.5)
        want = es.post(f"/{LOGS}/_count", {"query": {"match": {"request": p["product"]}}})["count"]
        c.equal(get(result, "response.hits.total.value"), want if want < 10000 else 10000,
                f'it finds all {want} entries for "{p["product"]}"')
        c.equal(len(get(result, "response.hits.hits", [])), p["size"], f"it returns {p['size']} hits")
        if reference.get("id"):
            es.send("DELETE", f"/_async_search/{reference['id']}")
