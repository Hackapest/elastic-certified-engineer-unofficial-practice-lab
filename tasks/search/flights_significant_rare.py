from lib.sampledata import FLIGHTS
from lib.tasklib import Task

DELAYS = ["Weather Delay", "Security Delay", "Late Aircraft Delay", "NAS Delay", "Carrier Delay"]


class FlightsSignificantRare(Task):
    id = "search-flights-significant-rare"
    title = "Unusual and rare terms (significant_terms, rare_terms)"
    covers = ["search.bucket-aggs.significant-terms", "search.bucket-aggs.rare-terms", "search.aggs.aggs-with-query"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"delay": rnd.choice(DELAYS), "sig_field": rnd.choice(["OriginWeather", "DestWeather", "Carrier"]),
                "rare_field": rnd.choice(["DestCityName", "OriginCityName"]), "max_count": rnd.choice([1, 2, 3])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Investigate the flights in `{FLIGHTS}` whose delay type (FlightDelayType) is "{p['delay']}". In one
request with no hits, return two aggregations over those flights:

  1. the values of {p['sig_field']} that are unusually common among these flights compared with
     all flights (the statistically significant ones, default scoring);
  2. the values of {p['rare_field']} that occur in at most {p['max_count']} of these flights (the rare
     ones, without guessing a terms size and sorting ascending).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "FlightDelayType": "{p['delay']}" }} }},
  "aggs": {{
    "unusual": {{ "significant_terms": {{ "field": "{p['sig_field']}" }} }},
    "rare": {{ "rare_terms": {{ "field": "{p['rare_field']}", "max_doc_count": {p['max_count']} }} }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # A plain terms aggregation: most common, not significant
        return self.solution(ctx).replace('"significant_terms"', '"terms"')
