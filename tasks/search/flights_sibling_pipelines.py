from lib.sampledata import FLIGHTS
from lib.tasklib import Task

GROUPS = ["Carrier", "DestWeather", "OriginWeather", "FlightDelayType"]
METRICS = {"average ticket price": ("avg", "AvgTicketPrice"), "average delay": ("avg", "FlightDelayMin"),
           "total distance": ("sum", "DistanceKilometers")}


class FlightsSiblingPipelines(Task):
    id = "search-flights-sibling-pipelines"
    title = "Statistics over buckets (max_bucket, min_bucket, avg_bucket, sum_bucket, stats_bucket)"
    covers = ["search.pipeline-aggs.max-bucket", "search.pipeline-aggs.min-bucket", "search.pipeline-aggs.avg-bucket",
              "search.pipeline-aggs.sum-bucket", "search.pipeline-aggs.stats-bucket", "search.bucket-aggs.terms"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        pipes = rnd.sample(["max_bucket", "min_bucket", "avg_bucket", "sum_bucket"], 2)
        return {"group": rnd.choice(GROUPS), "metric": rnd.choice(sorted(METRICS)), "pipes": pipes,
                "country": rnd.choice(["IT", "US", "JP", "CN", "CA", "DE"])}

    def prompt(self, ctx):
        p = ctx.p
        words = {"max_bucket": "the group with the highest value, and that value",
                 "min_bucket": "the group with the lowest value, and that value",
                 "avg_bucket": "the average of the per-group values",
                 "sum_bucket": "the sum of the per-group values"}
        wanted = "\n".join(f"  - {words[x]}" for x in p["pipes"])
        return f"""
For flights departing from the country "{p['country']}" (OriginCountry) in `{FLIGHTS}`, compute the
{p['metric']} ({METRICS[p['metric']][1]}) per {p['group']} (all values; there are fewer than 20).

Then, computed by Elasticsearch from those per-group values (not from the flights directly):
{wanted}
  - count, min, max, average and sum of the per-group values, in one aggregation

No hits.
"""

    def solution(self, ctx):
        p = ctx.p
        kind, field = METRICS[p["metric"]]
        pipes = "".join(f''',
    "{x}": {{ "{x}": {{ "buckets_path": "groups>metric" }} }}''' for x in p["pipes"])
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "OriginCountry": "{p['country']}" }} }},
  "aggs": {{
    "groups": {{
      "terms": {{ "field": "{p['group']}", "size": 20 }},
      "aggs": {{
        "metric": {{ "{kind}": {{ "field": "{field}" }} }}
      }}
    }}{pipes},
    "stats": {{ "stats_bucket": {{ "buckets_path": "groups>metric" }} }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # The statistics of the flights themselves instead of the per-group values
        kind, field = METRICS[ctx.p["metric"]]
        return self.solution(ctx).replace('"stats": { "stats_bucket": { "buckets_path": "groups>metric" } }',
                                          f'"stats": {{ "stats": {{ "field": "{field}" }} }}')
