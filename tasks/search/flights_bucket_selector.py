from lib.sampledata import FLIGHTS
from lib.tasklib import Task


class FlightsBucketSelector(Task):
    id = "search-flights-bucket-selector"
    title = "Filter and sort buckets by their metrics (bucket_selector, bucket_sort)"
    covers = ["search.pipeline-aggs.bucket-selector", "search.pipeline-aggs.bucket-sort",
              "search.bucket-aggs.terms", "search.metric-aggs.avg", "search.aggs.sub-aggregations"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        # Average delays cluster between 45 and 55 minutes and counts vary a lot, so these cut through
        min_flights = rnd.choice([40, 100, 350, 500])
        # (500 flights and 52 minutes leaves no country at all)
        min_delay = rnd.choice([45, 48, 50] if min_flights == 500 else [45, 48, 50, 52])
        return {"min_flights": min_flights, "min_delay": min_delay, "top": rnd.choice([3, 5, 8])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{FLIGHTS}`, look at destination countries (DestCountry). For each country, compute the
average delay in minutes (FlightDelayMin).

Return only countries that have more than {p['min_flights']} flights AND an average delay above
{p['min_delay']} minutes, sorted by average delay, highest first, and only the first {p['top']} of them.

Consider all countries, not just the 10 a terms aggregation returns by default (there are
fewer than 100). No hits, and no other aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 0,
  "aggs": {{
    "countries": {{
      "terms": {{ "field": "DestCountry", "size": 100 }},
      "aggs": {{
        "avg_delay": {{ "avg": {{ "field": "FlightDelayMin" }} }},
        "busy_and_late": {{
          "bucket_selector": {{
            "buckets_path": {{ "flights": "_count", "delay": "avg_delay" }},
            "script": "params.flights > {p['min_flights']} && params.delay > {p['min_delay']}"
          }}
        }},
        "worst_first": {{
          "bucket_sort": {{
            "sort": [{{ "avg_delay": {{ "order": "desc" }} }}],
            "size": {p['top']}
          }}
        }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Forgets the flight count condition (NL: 3 flights, 65 minutes average, then gets in)
        return self.solution(ctx).replace(f"params.flights > {ctx.p['min_flights']} && ", "")
