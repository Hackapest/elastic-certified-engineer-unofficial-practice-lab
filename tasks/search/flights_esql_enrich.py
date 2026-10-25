import json

from lib.sampledata import FLIGHTS
from lib.tasklib import Task

CITIES = ["Rome", "London", "Quito", "Osaka", "Seoul", "Tokyo", "Buenos Aires", "Bogota", "Shanghai", "Milan",
          "Paris", "Sydney", "Zurich", "Mumbai", "Moscow", "Toronto", "Chicago", "Vienna", "Dubai", "Madrid"]
REGIONS = ["Alpha", "Bravo", "Charlie"]


class FlightsEsqlEnrich(Task):
    id = "search-flights-esql-enrich"
    title = "Add data from an enrich policy in ES|QL (ENRICH)"
    covers = ["search.esql.command.enrich", "search.esql.enrich-esql",
              "search.esql.command.stats", "search.esql.functions.aggregation"]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        cities = rnd.sample(CITIES, 12)
        return {"index": f"city-regions-{iid}", "policy": f"city-regions-policy-{iid}",
                "region_of": {c: REGIONS[i % 3] for i, c in enumerate(cities)},
                "field": rnd.choice(["DestCityName", "OriginCityName"]),
                "metric": rnd.choice(["AvgTicketPrice", "FlightDelayMin", "DistanceKilometers"])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"mappings": {"properties": {
            "city": {"type": "keyword"}, "sales_region": {"type": "keyword"}, "manager": {"type": "keyword"}}}})
        bulk = "".join(json.dumps({"index": {}}) + "\n" +
                       json.dumps({"city": c, "sales_region": r, "manager": f"manager-{r.lower()}"}) + "\n"
                       for c, r in sorted(p["region_of"].items()))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")
        es.put(f"/_enrich/policy/{p['policy']}", {"match": {
            "indices": p["index"], "match_field": "city", "enrich_fields": ["sales_region", "manager"]}})
        es.post(f"/_enrich/policy/{p['policy']}/_execute?wait_for_completion=true", timeout=120)

    def prompt(self, ctx):
        p = ctx.p
        side = "destination" if p["field"] == "DestCityName" else "origin"
        return f"""
The enrich policy `{p['policy']}` (already executed) maps a city name (city) to its sales region
(sales_region) and manager, from the index `{p['index']}`. Look at them first.

Write an ES|QL query on `{FLIGHTS}` that uses this policy to look up the sales region of each
flight's {side} city ({p['field']}), and returns, for flights whose city has a sales region, one
row per sales region with these columns in this order:

  sales_region   the region
  flights        the number of flights
  avg_metric     the average {p['metric']}, rounded to 1 decimal

Sorted by sales_region, A to Z.
"""

    def solution(self, ctx):
        p = ctx.p
        return f'''
POST _query
{{
  "query": """
    FROM {FLIGHTS}
    | ENRICH {p['policy']} ON {p['field']} WITH sales_region
    | WHERE sales_region IS NOT NULL
    | STATS flights = COUNT(*), avg_metric = ROUND(AVG({p['metric']}), 1) BY sales_region
    | SORT sales_region
  """
}}
'''

    def wrong_answer(self, ctx):
        # Looks up the other city
        p = ctx.p
        other = "OriginCityName" if p["field"] == "DestCityName" else "DestCityName"
        return self.solution(ctx).replace(f"ON {p['field']}", f"ON {other}")
