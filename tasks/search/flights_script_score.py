from lib.sampledata import FLIGHT_CARRIERS, FLIGHTS
from lib.tasklib import Task


class FlightsScriptScore(Task):
    id = "search-flights-script-score"
    title = "Filter and score with Painless (script query, script_score)"
    covers = ["search.specialized.script", "search.specialized.script-score", "search.compound.bool"]
    answer = "query"
    compare = "hits_scored"

    def params(self, rnd, iid):
        return {"carrier": rnd.choice(FLIGHT_CARRIERS), "speed": rnd.choice([500, 600, 700, 800]),
                "per": rnd.choice([100, 1000]), "top": rnd.choice([10, 20])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{FLIGHTS}`, look at flights of the carrier "{p['carrier']}" (Carrier) that were slow: their average
speed, DistanceKilometers divided by the flight time in hours (FlightTimeMin / 60), is below
{p['speed']} km/h. Use a script for this condition (it compares two fields of the same document).

Score each of these flights by its price per {p['per']} km:

  score = AvgTicketPrice / DistanceKilometers * {p['per']}

(guard against a distance of 0 by dividing by at least 1 km). Only the script determines the
score. Return the {p['top']} highest-scoring flights, best first.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {FLIGHTS}/_search
{{
  "size": {p['top']},
  "query": {{
    "script_score": {{
      "query": {{
        "bool": {{
          "filter": [
            {{ "term": {{ "Carrier": "{p['carrier']}" }} }},
            {{ "script": {{ "script": {{
                "source": "doc['FlightTimeMin'].value > 0 && doc['DistanceKilometers'].value / (doc['FlightTimeMin'].value / 60) < params.speed",
                "params": {{ "speed": {p['speed']} }}
            }} }} }}
          ]
        }}
      }},
      "script": {{
        "source": "doc['AvgTicketPrice'].value / Math.max(doc['DistanceKilometers'].value, 1) * params.per",
        "params": {{ "per": {p['per']} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Fast flights instead of slow ones
        return self.solution(ctx).replace("< params.speed", ">= params.speed")
