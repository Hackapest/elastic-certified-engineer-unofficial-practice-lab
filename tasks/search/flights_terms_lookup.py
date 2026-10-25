import json

from lib.sampledata import FLIGHTS
from lib.tasklib import Task

CITIES = ["Zurich", "Xi'an", "Shanghai", "Winnipeg", "Tokyo", "Warsaw", "Verona", "Vienna", "Venice",
          "London", "Buenos Aires", "Sydney", "Paris", "Madrid", "Dublin", "Oslo", "Lima", "Seoul"]
WEATHER = ["Rain", "Heavy Fog", "Thunder & Lightning", "Hail", "Damaging Wind", "Cloudy"]


class FlightsTermsLookup(Task):
    id = "search-flights-terms-lookup"
    title = "Filter by values stored in another document (terms lookup)"
    covers = ["search.term.terms-lookup", "search.term.terms", "search.compound.bool"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        cities = rnd.sample(CITIES, 8)
        return {"index": f"watchlists-{iid}", "team": rnd.choice(["ops", "security", "finance"]),
                "mine": sorted(cities[:4]), "other": sorted(cities[4:]), "weather": rnd.choice(WEATHER)}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"mappings": {"properties": {"team": {"type": "keyword"},
                                                              "cities": {"type": "keyword"}}}})
        teams = [t for t in ["ops", "security", "finance"] if t != p["team"]]
        docs = [(p["team"], p["mine"]), (teams[0], p["other"]), (teams[1], p["other"][:2] + p["mine"][:1])]
        bulk = "".join(json.dumps({"index": {"_id": f"team-{t}"}}) + "\n" + json.dumps({"team": t, "cities": c}) + "\n"
                       for t, c in docs)
        ctx.es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds one watchlist document per team; the document with the ID
`team-{p['team']}` lists the destination cities the {p['team']} team watches (field "cities"). The list
changes often, so your query must read it from that document at search time instead of copying
the city names into the query.

Find the flights in `{FLIGHTS}` whose destination city (DestCityName) is on the {p['team']} team's
watchlist and whose destination weather (DestWeather) is "{p['weather']}".

Return all of them in one response (fewer than 1000).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 1000,
  "query": {{
    "bool": {{
      "filter": [
        {{ "terms": {{ "DestCityName": {{ "index": "{p['index']}", "id": "team-{p['team']}", "path": "cities" }} }} }},
        {{ "term": {{ "DestWeather": "{p['weather']}" }} }}
      ]
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        teams = [t for t in ["ops", "security", "finance"] if t != ctx.p["team"]]
        return self.solution(ctx).replace(f'"team-{ctx.p["team"]}"', f'"team-{teams[0]}"')
