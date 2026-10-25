from lib.sampledata import FLIGHTS, FLIGHT_CARRIERS
from lib.tasklib import Task, get, same_hits

CITIES = ["Rome", "London", "Quito", "Osaka", "Seoul", "Tokyo", "Buenos Aires", "Bogota", "Shanghai", "Milan"]
WEATHER = ["Rain", "Clear", "Sunny", "Cloudy"]


class FlightsConstantScore(Task):
    id = "search-flights-constant-score"
    title = "Score by conditions met (constant_score, minimum_should_match, ids)"
    covers = ["search.compound.constant-score", "search.compound.minimum-should-match", "search.term.ids",
              "search.compound.bool", "search.basics.query-filter-context"]
    answer = "query"

    def params(self, rnd, iid):
        points = rnd.sample([1, 2, 3, 4, 5], 3)
        return {"city": rnd.choice(CITIES), "carrier": rnd.choice(FLIGHT_CARRIERS), "weather": rnd.choice(WEATHER),
                "p_carrier": points[0], "p_weather": points[1], "p_ontime": points[2]}

    def excluded(self, ctx):
        """Two IDs of flights from the city that meet all three conditions (IDs differ per install)."""
        p = ctx.p
        r = ctx.es.post(f"/{FLIGHTS}/_search", {"size": 2, "sort": [{"FlightNum": "asc"}], "_source": False,
                                                "query": {"bool": {"filter": [
                                                    {"term": {"OriginCityName": p["city"]}},
                                                    {"term": {"Carrier": p["carrier"]}},
                                                    {"term": {"FlightDelay": False}}]}}})
        return [h["_id"] for h in get(r, "hits.hits", [])]

    def prompt(self, ctx):
        p = ctx.p
        ids = ", ".join(f'"{i}"' for i in self.excluded(ctx))
        return f"""
Rank the flights in `{FLIGHTS}` that depart from {p['city']} (OriginCityName). Each flight earns
points for these conditions:

  {p['p_carrier']} points   the carrier (Carrier) is "{p['carrier']}"
  {p['p_weather']} points   the destination weather (DestWeather) is "{p['weather']}"
  {p['p_ontime']} points   the flight was not delayed (FlightDelay is false)

A flight's score must be exactly the sum of its points (relevance of the terms plays no role), and
the departure city must not affect the score. Only return flights that meet at least 2 of the 3
conditions, and leave out the flights with these document IDs: {ids}.

Return all matching flights in one response, best first (there are fewer than 1000).
"""

    def solution(self, ctx):
        p = ctx.p
        ids = ", ".join(f'"{i}"' for i in self.excluded(ctx))
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 1000,
  "query": {{
    "bool": {{
      "filter": [ {{ "term": {{ "OriginCityName": "{p['city']}" }} }} ],
      "must_not": [ {{ "ids": {{ "values": [{ids}] }} }} ],
      "should": [
        {{ "constant_score": {{ "filter": {{ "term": {{ "Carrier": "{p['carrier']}" }} }}, "boost": {p['p_carrier']} }} }},
        {{ "constant_score": {{ "filter": {{ "term": {{ "DestWeather": "{p['weather']}" }} }}, "boost": {p['p_weather']} }} }},
        {{ "constant_score": {{ "filter": {{ "term": {{ "FlightDelay": false }} }}, "boost": {p['p_ontime']} }} }}
      ],
      "minimum_should_match": 2
    }}
  }}
}}
"""

    def grade(self, ctx, c, answer, reference):
        same_hits(c, answer, reference, ordered=False)
        scores = lambda r: {h["_id"]: round(h.get("_score") or 0.0, 4) for h in get(r, "hits.hits", [])}
        got, want = scores(answer), scores(reference)
        wrong = [i for i in want if i in got and got[i] != want[i]]
        c.check(not wrong and got.keys() == want.keys(), "each flight's score is the sum of its points",
                f"e.g. flight {wrong[0]}: expected {want[wrong[0]]}, got {got[wrong[0]]}" if wrong else None)

    def wrong_answer(self, ctx):
        # At least one condition instead of two
        return self.solution(ctx).replace('"minimum_should_match": 2', '"minimum_should_match": 1')
