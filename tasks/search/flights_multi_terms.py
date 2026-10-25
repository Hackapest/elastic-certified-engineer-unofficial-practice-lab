from lib.sampledata import FLIGHTS
from lib.tasklib import Task

METRICS = {"average delay in minutes": ("avg", "FlightDelayMin"), "average ticket price": ("avg", "AvgTicketPrice"),
           "longest distance": ("max", "DistanceKilometers"), "total distance": ("sum", "DistanceKilometers")}


class FlightsMultiTerms(Task):
    id = "search-flights-multi-terms"
    title = "Buckets per combination of two fields (multi_terms)"
    covers = ["search.bucket-aggs.multi-terms", "search.aggs.sub-aggregations", "search.metric-aggs.avg"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"fields": rnd.choice([["Carrier", "DestWeather"], ["OriginWeather", "DestWeather"],
                                      ["Carrier", "FlightDelayType"], ["DestCountry", "Carrier"]]),
                "metric": rnd.choice(sorted(METRICS)), "top": rnd.choice([5, 8, 10]),
                "min_count": rnd.choice([20, 50, 100])}

    def prompt(self, ctx):
        p = ctx.p
        a, b = p["fields"]
        return f"""
In `{FLIGHTS}`, find the {p['top']} combinations of {a} and {b} (in that order) with the highest
{p['metric']} ({METRICS[p['metric']][1]}), highest first. Only consider combinations with at
least {p['min_count']} flights.

Use one bucket aggregation over both fields, with the metric as its sub-aggregation. No hits.
"""

    def solution(self, ctx):
        p = ctx.p
        a, b = p["fields"]
        kind, field = METRICS[p["metric"]]
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 0,
  "aggs": {{
    "combos": {{
      "multi_terms": {{
        "terms": [ {{ "field": "{a}" }}, {{ "field": "{b}" }} ],
        "size": {p['top']},
        "min_doc_count": {p['min_count']},
        "order": {{ "metric": "desc" }}
      }},
      "aggs": {{
        "metric": {{ "{kind}": {{ "field": "{field}" }} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # The default order (by number of flights)
        return self.solution(ctx).replace(',\n        "order": { "metric": "desc" }', "")
