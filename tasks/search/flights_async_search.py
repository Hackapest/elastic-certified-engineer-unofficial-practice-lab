from lib.sampledata import FLIGHTS
from lib.tasklib import Task, get, same_aggs

KEEP_ALIVE = {"30m": 30, "1h": 60, "2h": 120, "1d": 1440}


class FlightsAsyncSearch(Task):
    id = "search-flights-async-search"
    title = "Run an aggregation as an async search and fetch it later"
    covers = ["search.async.submit", "search.async.get-status-delete", "search.bucket-aggs.terms",
              "search.metric-aggs.avg", "search.metric-aggs.max"]
    answer = "query"

    def params(self, rnd, iid):
        return {"keep_alive": rnd.choice(sorted(KEEP_ALIVE)), "field": rnd.choice(["AvgTicketPrice", "FlightDelayMin",
                                                                                   "DistanceKilometers"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Pretend `{FLIGHTS}` is huge, so this report must run as an asynchronous search:

  For each carrier (Carrier): the average and the maximum {p['field']}. No hits, only the results.

Submit it so that the results are kept for {p['keep_alive']} after it finishes, then fetch the results with
a separate request using the search's ID. Hand in both requests; the second one (the fetch) is
graded. Also try the status API on it.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST {FLIGHTS}/_async_search?keep_alive={p['keep_alive']}
{{
  "size": 0,
  "aggs": {{
    "carriers": {{
      "terms": {{ "field": "Carrier" }},
      "aggs": {{
        "avg_value": {{ "avg": {{ "field": "{p['field']}" }} }},
        "max_value": {{ "max": {{ "field": "{p['field']}" }} }}
      }}
    }}
  }}
}}

# then, with the "id" from the response:
# GET _async_search/<id>
"""

    def wrong_answer(self, ctx):
        return self.solution(ctx).replace(f"keep_alive={ctx.p['keep_alive']}", "keep_alive=1m")

    def grade(self, ctx, c, answer, reference):
        if reference.get("id") and reference.get("id") != answer.get("id"):
            ctx.es.send("DELETE", f"/_async_search/{reference['id']}")   # don't keep the reference's results
        is_async = isinstance(answer, dict) and "is_running" in answer
        if not c.check(is_async, "the answer is an async search response",
                       "the graded (last) request should be GET _async_search/<id>"):
            return
        same_aggs(c, answer.get("response", {}), reference.get("response", {}))
        kept = (answer.get("expiration_time_in_millis", 0) - answer.get("start_time_in_millis", 0)) / 60000
        want = KEEP_ALIVE[ctx.p["keep_alive"]]
        c.check(abs(kept - want) <= max(2, want * 0.05), f"results are kept for {ctx.p['keep_alive']}",
                f"they expire after about {kept:.0f} minutes")
