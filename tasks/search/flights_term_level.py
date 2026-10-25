from lib.sampledata import FLIGHT_CARRIERS, FLIGHTS
from lib.tasklib import Task


class FlightsTermLevel(Task):
    id = "search-flights-term-level"
    title = "Exact-value queries: terms, prefix, regexp, range"
    covers = ["search.term.terms", "search.term.prefix", "search.term.regexp", "search.term.range",
              "search.compound.bool"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        return {
            "carriers": sorted(rnd.sample(FLIGHT_CARRIERS, 2)),
            "city_prefix": rnd.choice(["V", "S", "T", "B", "M"]),
            "digits": rnd.choice([1, 2]),
            "min_price": rnd.choice([300, 500, 700]),
        }

    def prompt(self, ctx):
        p = ctx.p
        what = "a digit" if p["digits"] == 1 else "two digits"
        return f"""
In `{FLIGHTS}`, find all flights that:

  - are operated by {p['carriers'][0]} or {p['carriers'][1]} (Carrier)
  - fly to a city whose name starts with "{p['city_prefix']}" (DestCityName, case-sensitive)
  - have a flight number (FlightNum) that starts with {what}
  - cost more than {p['min_price']} (AvgTicketPrice)

Return all of them in one response; there are fewer than 500.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 500,
  "query": {{
    "bool": {{
      "filter": [
        {{ "terms": {{ "Carrier": ["{p['carriers'][0]}", "{p['carriers'][1]}"] }} }},
        {{ "prefix": {{ "DestCityName": "{p['city_prefix']}" }} }},
        {{ "regexp": {{ "FlightNum": "[0-9]{{{p['digits']}}}.*" }} }},
        {{ "range": {{ "AvgTicketPrice": {{ "gt": {p['min_price']} }} }} }}
      ]
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Only one digit required where two were asked, or vice versa
        p = ctx.p
        return self.solution(ctx).replace(f"[0-9]{{{p['digits']}}}", f"[0-9]{{{3 - p['digits']}}}")
