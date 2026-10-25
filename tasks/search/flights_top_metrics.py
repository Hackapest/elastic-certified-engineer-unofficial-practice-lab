from lib.sampledata import FLIGHTS
from lib.tasklib import Task, get, _round

ORIGINS = ["IT", "US", "JP", "CN", "CA", "DE", "IN", "AU", "GB"]
METRICS = [["AvgTicketPrice", "FlightDelayMin"], ["DistanceKilometers", "FlightTimeMin"],
           ["AvgTicketPrice", "DistanceKilometers"]]


def top_values(response):
    """{bucket key: [(sort values, metrics)]} of the first bucket aggregation's top_metrics sub-aggregation."""
    result = {}
    for agg in (get(response, "aggregations") or {}).values():
        for bucket in agg.get("buckets", []) if isinstance(agg, dict) else []:
            for child in bucket.values():
                if isinstance(child, dict) and isinstance(child.get("top"), list):
                    result[bucket["key"]] = [
                        ([_round(v) for v in t.get("sort", [])],
                         {k: _round(v) for k, v in sorted(t.get("metrics", {}).items())})
                        for t in child["top"]]
    return result


class FlightsTopMetrics(Task):
    id = "search-flights-top-metrics"
    title = "Values from the latest document per group (top_metrics)"
    covers = ["search.metric-aggs.top-metrics", "search.bucket-aggs.terms"]
    answer = "query"

    def params(self, rnd, iid):
        return {"origin": rnd.choice(ORIGINS), "metrics": rnd.choice(METRICS), "which": rnd.choice(["latest", "earliest"]),
                "n": rnd.choice([1, 2, 3])}

    def prompt(self, ctx):
        p = ctx.p
        flights = "flight" if p["n"] == 1 else f"{p['n']} flights"
        return f"""
For flights in `{FLIGHTS}` departing from the country "{p['origin']}" (OriginCountry), show per
carrier (Carrier) the {p['metrics'][0]} and {p['metrics'][1]} of its {p['which']} {flights} (by timestamp).

Use the top_metrics aggregation, with exactly these two metrics. No hits.
"""

    def solution(self, ctx):
        p = ctx.p
        order = "desc" if p["which"] == "latest" else "asc"
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "OriginCountry": "{p['origin']}" }} }},
  "aggs": {{
    "carriers": {{
      "terms": {{ "field": "Carrier" }},
      "aggs": {{
        "last_flight": {{
          "top_metrics": {{
            "metrics": [ {{ "field": "{p['metrics'][0]}" }}, {{ "field": "{p['metrics'][1]}" }} ],
            "sort": {{ "timestamp": "{order}" }},
            "size": {p['n']}
          }}
        }}
      }}
    }}
  }}
}}
"""

    def grade(self, ctx, c, answer, reference):
        got, want = top_values(answer), top_values(reference)
        if not c.check(got, "returns top_metrics results per carrier",
                       "expected a terms aggregation on Carrier with a top_metrics sub-aggregation"):
            return
        c.equal(sorted(got), sorted(want), "returns every carrier")
        wrong = [k for k in want if k in got and got[k] != want[k]]
        c.check(not wrong, "returns the expected flights' values",
                f"for {wrong[0]}: expected {want[wrong[0]]}, got {got[wrong[0]]}" if wrong else None)

    def wrong_answer(self, ctx):
        # Sorted the wrong way
        s = self.solution(ctx)
        return s.replace('"timestamp": "desc"', '"timestamp": "asc"') if '"desc"' in s else \
            s.replace('"timestamp": "asc"', '"timestamp": "desc"')
