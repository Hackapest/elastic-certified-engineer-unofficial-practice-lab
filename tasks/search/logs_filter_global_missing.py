from lib.sampledata import LOG_OS, LOGS
from lib.tasklib import Task

TAGS = ["security", "warning", "error", "login"]
METRICS = {"average": "avg", "total": "sum", "largest": "max"}


class LogsFilterGlobalMissing(Task):
    id = "search-logs-filter-global-missing"
    title = "Single-bucket aggregations: filter, global and missing"
    covers = ["search.bucket-aggs.filter", "search.bucket-aggs.global", "search.bucket-aggs.missing",
              "search.aggs.aggs-with-query"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"os": rnd.choice(LOG_OS), "tag": rnd.choice(TAGS), "metric": rnd.choice(sorted(METRICS))}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Build one request on `{LOGS}` whose query selects the requests from machines running
"{p['os']}" (machine.os.keyword). It must return no hits, and exactly these three aggregations:

  1. the {p['metric']} bytes (bytes) of ALL requests in the data stream, whatever the operating
     system, to compare against (without a second request);
  2. for the "{p['os']}" requests tagged "{p['tag']}" (tags.keyword): their number and their
     {p['metric']} bytes;
  3. the number of "{p['os']}" requests that have no memory value (field memory is missing).
"""

    def solution(self, ctx):
        p = ctx.p
        m = METRICS[p["metric"]]
        return f"""
GET {LOGS}/_search
{{
  "size": 0,
  "query": {{ "term": {{ "machine.os.keyword": "{p['os']}" }} }},
  "aggs": {{
    "everything": {{
      "global": {{}},
      "aggs": {{ "bytes": {{ "{m}": {{ "field": "bytes" }} }} }}
    }},
    "tagged": {{
      "filter": {{ "term": {{ "tags.keyword": "{p['tag']}" }} }},
      "aggs": {{ "bytes": {{ "{m}": {{ "field": "bytes" }} }} }}
    }},
    "no_memory": {{ "missing": {{ "field": "memory" }} }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # A filter that matches everything is still limited by the query, unlike global
        return self.solution(ctx).replace('"global": {}', '"filter": { "match_all": {} }')
