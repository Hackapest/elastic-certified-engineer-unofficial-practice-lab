from datetime import datetime, timedelta, timezone

from lib.sampledata import LOGS
from lib.tasklib import Task, get


def first_day(es):
    """The first day of the web logs (the sample data's dates depend on the install date)."""
    r = es.post(f"/{LOGS}/_search", {"size": 0, "aggs": {"first": {"min": {"field": "@timestamp"}}}})
    ts = datetime.fromtimestamp(get(r, "aggregations.first.value") / 1000, tz=timezone.utc)
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


class LogsDateRange(Task):
    id = "search-logs-date-range"
    title = "Buckets for given date ranges (date_range with date math)"
    covers = ["search.bucket-aggs.date-range", "search.term.range", "search.metric-aggs.cardinality"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"offset": rnd.choice([3, 7, 10, 14]), "days": rnd.choice([7, 14]),
                "metric": rnd.choice(["total bytes (bytes)", "number of distinct client IPs (clientip)"])}

    def dates(self, ctx):
        start = first_day(ctx.es) + timedelta(days=ctx.p["offset"])
        fmt = lambda d: d.strftime("%Y-%m-%d")
        return fmt(start), fmt(start + timedelta(days=ctx.p["days"])), fmt(start + timedelta(days=2 * ctx.p["days"]))

    def prompt(self, ctx):
        p = ctx.p
        a, b, c = self.dates(ctx)
        return f"""
Compare three periods of traffic in `{LOGS}` (by @timestamp, UTC), in one aggregation:

  before    everything before {a}
  period 1  from {a} (included) to {b} (excluded)
  period 2  from {b} (included) to {c} (excluded)

and, per period, the {p['metric']}. Nothing after {c} counts. No hits. (Write the dates as you like,
e.g. "{a}" or "{a}||+{p['days']}d".)
"""

    def solution(self, ctx):
        p = ctx.p
        a, b, c = self.dates(ctx)
        metric = ('"sum": { "field": "bytes" }' if p["metric"].startswith("total")
                  else '"cardinality": { "field": "clientip" }')
        return f"""
GET {LOGS}/_search
{{
  "size": 0,
  "aggs": {{
    "periods": {{
      "date_range": {{
        "field": "@timestamp",
        "ranges": [
          {{ "key": "before", "to": "{a}" }},
          {{ "key": "period 1", "from": "{a}", "to": "{b}" }},
          {{ "key": "period 2", "from": "{b}", "to": "{c}" }}
        ]
      }},
      "aggs": {{
        "metric": {{ {metric} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Period 2 open-ended
        a, b, c = self.dates(ctx)
        return self.solution(ctx).replace(f'"from": "{b}", "to": "{c}"', f'"from": "{b}"')
