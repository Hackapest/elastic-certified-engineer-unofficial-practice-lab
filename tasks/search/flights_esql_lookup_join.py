import json

from lib.sampledata import FLIGHT_CARRIERS, FLIGHTS
from lib.tasklib import Task

ALLIANCES = ["Star Cluster", "OneShard", "SkyNode", "Replica Union"]


class FlightsEsqlLookupJoin(Task):
    id = "search-flights-esql-lookup-join"
    title = "Join flights with a lookup index (ES|QL LOOKUP JOIN)"
    covers = ["search.esql.lookup-join-index", "search.esql.command.lookup-join", "search.esql.command.stats",
              "search.esql.command.sort", "search.esql.command.keep", "search.esql.functions.aggregation",
              "search.esql.functions.conditional", "search.esql.command.where"]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        alliances = rnd.sample(ALLIANCES, 2)
        carriers = list(FLIGHT_CARRIERS)
        rnd.shuffle(carriers)
        return {"index": f"carrier-info-{iid}",
                "alliance_of": {c: alliances[i % 2] for i, c in enumerate(carriers)},
                "weather": rnd.choice(["Rain", "Heavy Fog", "Thunder & Lightning", "Hail"])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"settings": {"index.mode": "lookup"},
                                  "mappings": {"properties": {"Carrier": {"type": "keyword"},
                                                              "alliance": {"type": "keyword"}}}})
        bulk = "".join(json.dumps({"index": {}}) + "\n" + json.dumps({"Carrier": c, "alliance": a}) + "\n"
                       for c, a in sorted(p["alliance_of"].items()))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The lookup index `{p['index']}` maps each airline (Carrier) to its alliance (alliance). Look at it first.

Write an ES|QL query on `{FLIGHTS}` that adds each flight's alliance from that index, and
returns, for flights whose origin weather (OriginWeather) was "{p['weather']}", one row per alliance
with these columns in this order:

  alliance      the alliance
  flights       the number of flights
  cancelled     how many of them were cancelled (Cancelled)

Sorted by alliance, A to Z. Run it with the _query API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f'''
POST _query
{{
  "query": """
    FROM {FLIGHTS}
    | WHERE OriginWeather == "{p['weather']}"
    | LOOKUP JOIN {p['index']} ON Carrier
    | STATS flights = COUNT(*), cancelled = COUNT(CASE(Cancelled, 1, null)) BY alliance
    | SORT alliance
    | KEEP alliance, flights, cancelled
  """
}}
'''

    def wrong_answer(self, ctx):
        # Counts all flights instead of the cancelled ones
        return self.solution(ctx).replace("COUNT(CASE(Cancelled, 1, null))", "COUNT(*)")
