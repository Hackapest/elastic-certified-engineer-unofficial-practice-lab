from lib.sampledata import LOGS
from lib.tasklib import Task

BLOCKS = ["0.0.0.0/3", "32.0.0.0/3", "64.0.0.0/3", "96.0.0.0/3", "128.0.0.0/3", "160.0.0.0/3", "192.0.0.0/3"]


class LogsIpRange(Task):
    id = "search-logs-ip-range"
    title = "Traffic per network and over time (ip_range, auto_date_histogram)"
    covers = ["search.bucket-aggs.ip-range", "search.bucket-aggs.auto-date-histogram", "search.metric-aggs.sum",
              "search.aggs.sub-aggregations"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"blocks": sorted(rnd.sample(BLOCKS, 2), key=BLOCKS.index), "buckets": rnd.choice([5, 10, 20]),
                "response": rnd.choice(["200", "404", "503"])}

    def prompt(self, ctx):
        p = ctx.p
        a, b = p["blocks"]
        return f"""
For the requests in `{LOGS}` with response code "{p['response']}" (response.keyword), report per
client network (clientip) in one aggregation:

  - the network {a}
  - the network {b}

and for each network: the total bytes (bytes), and the number of requests over time
(@timestamp) as a histogram where Elasticsearch picks the interval itself so that there are at
most {p['buckets']} buckets.

No hits, no other aggregations.
"""

    def solution(self, ctx):
        p = ctx.p
        a, b = p["blocks"]
        return f"""
GET {LOGS}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "response.keyword": "{p['response']}" }} }},
  "aggs": {{
    "networks": {{
      "ip_range": {{
        "field": "clientip",
        "ranges": [ {{ "mask": "{a}" }}, {{ "mask": "{b}" }} ]
      }},
      "aggs": {{
        "bytes": {{ "sum": {{ "field": "bytes" }} }},
        "over_time": {{ "auto_date_histogram": {{ "field": "@timestamp", "buckets": {p['buckets']} }} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Networks half the size (/4 instead of /3)
        return self.solution(ctx).replace('/3"', '/4"')
