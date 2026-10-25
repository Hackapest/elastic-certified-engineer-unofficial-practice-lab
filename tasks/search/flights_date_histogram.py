from lib.sampledata import FLIGHT_CARRIERS, FLIGHTS
from lib.tasklib import Task

INTERVALS = {"day": "day", "week": "week"}
TIME_ZONES = ["Europe/Berlin", "America/New_York", "Asia/Tokyo", "UTC"]


class FlightsDateHistogram(Task):
    id = "search-flights-date-histogram"
    title = "Flights over time with a running total (date_histogram, cumulative_sum)"
    covers = ["search.bucket-aggs.date-histogram", "search.pipeline-aggs.cumulative-sum",
              "search.metric-aggs.sum", "search.aggs.sub-aggregations", "search.aggs.aggs-with-query"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"carrier": rnd.choice(FLIGHT_CARRIERS), "interval": rnd.choice(sorted(INTERVALS)),
                "time_zone": rnd.choice(TIME_ZONES)}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{FLIGHTS}`, for flights operated by {p['carrier']} (Carrier), compute per calendar {p['interval']}
(timestamp, in the time zone {p['time_zone']}):

  - the number of flights (the bucket's document count)
  - the total distance flown in kilometers (DistanceKilometers)
  - the running total of that distance from the first {p['interval']} up to this one

No hits, only the aggregation results, and no other aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 0,
  "query": {{
    "term": {{ "Carrier": "{p['carrier']}" }}
  }},
  "aggs": {{
    "per_{p['interval']}": {{
      "date_histogram": {{
        "field": "timestamp",
        "calendar_interval": "{p['interval']}",
        "time_zone": "{p['time_zone']}"
      }},
      "aggs": {{
        "distance": {{ "sum": {{ "field": "DistanceKilometers" }} }},
        "running_distance": {{ "cumulative_sum": {{ "buckets_path": "distance" }} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Forgets the time zone (unless it's UTC, then uses a different one)
        tz = ctx.p["time_zone"]
        return self.solution(ctx).replace(f'"time_zone": "{tz}"',
                                          '"time_zone": "Asia/Tokyo"' if tz == "UTC" else '"time_zone": "UTC"')
