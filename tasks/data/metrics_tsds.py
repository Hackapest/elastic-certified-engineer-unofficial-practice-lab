import datetime
import json

from lib.tasklib import Task, field_mapping, get

HOSTS = ["web-01", "web-02", "db-01"]


class MetricsTsds(Task):
    id = "data-metrics-tsds"
    title = "Exam-style: a time series data stream with dimensions, metrics, and downsampling in ILM"
    covers = ["data.templates.tsds", "data.index.index-modes", "data.ilm.action.downsample",
              "data.templates.component", "data.templates.data-stream-template", "data.ilm.policy-in-template",
              "data.ilm.action.rollover", "data.templates.use-data-stream"]
    size = "exam"
    answer = "state"

    def params(self, rnd, iid):
        return {"stream": f"hostmetrics-{iid}", "template": f"hostmetrics-{iid}",
                "component": f"hostmetrics-mappings-{iid}", "policy": f"hostmetrics-policy-{iid}",
                "rollover": rnd.choice(["1d", "12h"]), "warm": rnd.choice(["2d", "7d"]),
                "interval": rnd.choice(["1h", "30m", "10m"]), "delete": rnd.choice(["30d", "90d"]),
                "region": rnd.choice(["eu-west", "us-east", "ap-south"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Host metrics must be stored as a time series data stream named `{p['stream']}`, which stores
metrics compactly and can be downsampled.

  1. Component template `{p['component']}` with this mapping:
       @timestamp        date
       host.name         keyword, a time series dimension
       region            keyword, a time series dimension
       cpu.pct           double, a gauge metric
       net.bytes_in      long, a counter metric
  2. ILM policy `{p['policy']}`: in the hot phase roll over after {p['rollover']}; in the warm phase,
     {p['warm']} after rollover, downsample the data to {p['interval']} intervals; delete it {p['delete']}
     after rollover.
  3. Index template `{p['template']}` that turns `{p['stream']}` into a time series data stream
     using the component template and the policy.
  4. Index one document per host for {', '.join(HOSTS)} (region {p['region']}) into the data stream,
     with the current time as @timestamp (any cpu.pct and net.bytes_in values).
"""

    def solution(self, ctx):
        p = ctx.p
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        docs = "\n".join('{ "create": {} }\n' + json.dumps({
            "@timestamp": (now - datetime.timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
            "host": {"name": h}, "region": p["region"], "cpu": {"pct": 0.25 + i / 10},
            "net": {"bytes_in": 1000 * (i + 1)}}) for i, h in enumerate(HOSTS))
        return f"""
PUT _component_template/{p['component']}
{{
  "template": {{
    "mappings": {{
      "properties": {{
        "@timestamp": {{ "type": "date" }},
        "host": {{ "properties": {{ "name": {{ "type": "keyword", "time_series_dimension": true }} }} }},
        "region": {{ "type": "keyword", "time_series_dimension": true }},
        "cpu": {{ "properties": {{ "pct": {{ "type": "double", "time_series_metric": "gauge" }} }} }},
        "net": {{ "properties": {{ "bytes_in": {{ "type": "long", "time_series_metric": "counter" }} }} }}
      }}
    }}
  }}
}}

PUT _ilm/policy/{p['policy']}
{{
  "policy": {{
    "phases": {{
      "hot": {{ "actions": {{ "rollover": {{ "max_age": "{p['rollover']}" }} }} }},
      "warm": {{
        "min_age": "{p['warm']}",
        "actions": {{ "downsample": {{ "fixed_interval": "{p['interval']}" }} }}
      }},
      "delete": {{ "min_age": "{p['delete']}", "actions": {{ "delete": {{}} }} }}
    }}
  }}
}}

PUT _index_template/{p['template']}
{{
  "index_patterns": ["{p['stream']}*"],
  "data_stream": {{}},
  "priority": 500,
  "composed_of": ["{p['component']}"],
  "template": {{
    "settings": {{
      "index.mode": "time_series",
      "index.lifecycle.name": "{p['policy']}"
    }}
  }}
}}

POST {p['stream']}/_bulk?refresh=true
{docs}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/_ilm/policy/{p['policy']}")
        if c.check(status == 200, f"policy {p['policy']} exists"):
            phases = get(response, f"{p['policy']}.policy.phases", {})
            c.equal(get(phases, "hot.actions.rollover.max_age"), p["rollover"], f"hot: roll over after {p['rollover']}")
            c.equal((get(phases, "warm.min_age"), get(phases, "warm.actions.downsample.fixed_interval")),
                    (p["warm"], p["interval"]), f"warm: downsample to {p['interval']} after {p['warm']}")
            c.equal((get(phases, "delete.min_age"), "delete" in get(phases, "delete.actions", {})),
                    (p["delete"], True), f"delete after {p['delete']}")
        status, response = es.send("GET", f"/_index_template/{p['template']}")
        if c.check(status == 200, f"index template {p['template']} exists"):
            c.check(p["component"] in get(response, "index_templates.0.index_template.composed_of", []),
                    "the index template uses the component template")
        c.check(es.send("GET", f"/_component_template/{p['component']}")[0] == 200,
                f"component template {p['component']} exists")
        status, response = es.send("GET", f"/_data_stream/{p['stream']}")
        if not c.check(status == 200, f"data stream {p['stream']} exists"):
            return
        ds = response["data_streams"][0]
        c.equal(ds.get("index_mode"), "time_series", "it is a time series data stream")
        c.equal(ds.get("ilm_policy"), p["policy"], "it is managed by the policy")
        expected = {"host.name": ("dimension", "keyword"), "region": ("dimension", "keyword"),
                    "cpu.pct": ("gauge", "double"), "net.bytes_in": ("counter", "long")}
        for field, (role, ftype) in expected.items():
            m = field_mapping(es, p["stream"], field) or {}
            got = "dimension" if m.get("time_series_dimension") else m.get("time_series_metric")
            c.equal((got, m.get("type")), (role, ftype), f"{field} is a {ftype} {role}")
        body = json.dumps({"size": 0, "aggs": {"hosts": {"terms": {"field": "host.name"}}}}).encode()
        result = es.send("POST", f"/{p['stream']}/_search", body, "application/json")[1] or {}
        hosts = sorted(b["key"] for b in get(result, "aggregations.hosts.buckets", []))
        c.equal(hosts, sorted(HOSTS), "the data stream has documents for every host")
