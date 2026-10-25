from lib.sampledata import FLIGHT_CARRIERS, FLIGHTS
from lib.tasklib import Task

# City centres (not the airports), with a radius that catches several airports
PLACES = {"Paris": (48.8566, 2.3522, [300, 500]), "Milan": (45.4642, 9.19, [150, 300]),
          "Tokyo": (35.6762, 139.6503, [100, 400]), "Munich": (48.1351, 11.582, [200, 400]),
          "Seoul": (37.5665, 126.978, [100, 300]), "Toronto": (43.6532, -79.3832, [300, 600])}
REGIONS = {  # name: (top, left, bottom, right)
    "the Americas": (70, -170, -60, -30), "Europe": (72, -25, 35, 45), "Asia": (60, 45, -10, 150)}


class FlightsGeoDistance(Task):
    id = "search-flights-geo-distance"
    title = "Flights near a place, sorted by distance (geo_distance, geo_bounding_box, geo sort)"
    covers = ["search.geo.geo-distance", "search.geo.geo-bounding-box", "search.results.sort-advanced"]
    answer = "query"
    compare = "hits_ordered"

    def params(self, rnd, iid):
        place = rnd.choice(sorted(PLACES))
        return {"place": place, "radius": rnd.choice(PLACES[place][2]),
                "region": rnd.choice(sorted(REGIONS)), "top": rnd.choice([10, 20, 30])}

    def prompt(self, ctx):
        p = ctx.p
        lat, lon, _ = PLACES[p["place"]]
        top, left, bottom, right = REGIONS[p["region"]]
        return f"""
In `{FLIGHTS}`, find flights:
  - whose destination airport (DestLocation) is within {p['radius']} km of the centre of {p['place']}
    (lat {lat}, lon {lon});
  - that depart from {p['region']}, defined as the box with top-left corner (lat {top}, lon {left})
    and bottom-right corner (lat {bottom}, lon {right}) for the origin airport (OriginLocation).

Return the first {p['top']}, sorted by the distance of the destination airport from the centre of
{p['place']} (closest first), and for the same distance by AvgTicketPrice (cheapest first).
"""

    def solution(self, ctx):
        p = ctx.p
        lat, lon, _ = PLACES[p["place"]]
        top, left, bottom, right = REGIONS[p["region"]]
        return f"""
GET {FLIGHTS}/_search
{{
  "size": {p['top']},
  "query": {{
    "bool": {{
      "filter": [
        {{ "geo_distance": {{ "distance": "{p['radius']}km", "DestLocation": {{ "lat": {lat}, "lon": {lon} }} }} }},
        {{ "geo_bounding_box": {{ "OriginLocation": {{
            "top_left": {{ "lat": {top}, "lon": {left} }},
            "bottom_right": {{ "lat": {bottom}, "lon": {right} }} }} }} }}
      ]
    }}
  }},
  "sort": [
    {{ "_geo_distance": {{ "DestLocation": {{ "lat": {lat}, "lon": {lon} }}, "order": "asc", "unit": "km" }} }},
    {{ "AvgTicketPrice": "asc" }}
  ]
}}
"""

    def wrong_answer(self, ctx):
        # Farthest first
        return self.solution(ctx).replace('"order": "asc", "unit": "km"', '"order": "desc", "unit": "km"')
