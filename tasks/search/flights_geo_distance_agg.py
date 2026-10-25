from lib.sampledata import FLIGHTS
from lib.tasklib import Task

CITIES = {"Rome": (41.9028, 12.4964), "London": (51.5074, -0.1278), "Chicago": (41.8781, -87.6298),
          "Tokyo": (35.6762, 139.6503), "Sydney": (-33.8688, 151.2093), "Buenos Aires": (-34.6037, -58.3816)}
RINGS = [[1000, 5000], [2000, 8000], [500, 3000], [3000, 10000]]


class FlightsGeoDistanceAgg(Task):
    id = "search-flights-geo-distance-agg"
    title = "Rings of distance around a point (geo_distance aggregation)"
    covers = ["search.bucket-aggs.geo-distance", "search.metric-aggs.avg", "search.aggs.sub-aggregations"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"city": rnd.choice(sorted(CITIES)), "rings": rnd.choice(RINGS),
                "field": rnd.choice(["OriginLocation", "DestLocation"]),
                "metric": rnd.choice(["AvgTicketPrice", "FlightDelayMin"]), "cancelled": rnd.choice([True, False])}

    def prompt(self, ctx):
        p = ctx.p
        lat, lon = CITIES[p["city"]]
        a, b = p["rings"]
        which = "origin" if p["field"] == "OriginLocation" else "destination"
        flights = "cancelled flights" if p["cancelled"] else "flights that were not cancelled"
        return f"""
A map shows {flights} (Cancelled) in `{FLIGHTS}` grouped by how far their {which} airport
({p['field']}) is from {p['city']} (lat {lat}, lon {lon}), in kilometers:

  closer than {a} km;  {a} to {b} km;  {b} km or more

For each ring: the number of flights and the average {p['metric']}. No hits. Use distances in
kilometers in the aggregation.
"""

    def solution(self, ctx):
        p = ctx.p
        lat, lon = CITIES[p["city"]]
        a, b = p["rings"]
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "Cancelled": {str(p['cancelled']).lower()} }} }},
  "aggs": {{
    "rings": {{
      "geo_distance": {{
        "field": "{p['field']}",
        "origin": {{ "lat": {lat}, "lon": {lon} }},
        "unit": "km",
        "ranges": [ {{ "to": {a} }}, {{ "from": {a}, "to": {b} }}, {{ "from": {b} }} ]
      }},
      "aggs": {{
        "avg_metric": {{ "avg": {{ "field": "{p['metric']}" }} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Distances taken as meters (the default unit)
        return self.solution(ctx).replace('"unit": "km",\n', "")
