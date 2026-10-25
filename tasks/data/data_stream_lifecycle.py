from lib.tasklib import Task, get


class DataStreamLifecycle(Task):
    id = "data-data-stream-lifecycle"
    title = "Retention with the data stream lifecycle instead of ILM"
    covers = ["data.ilm.data-stream-lifecycle", "data.templates.modify-data-stream", "data.templates.use-data-stream"]
    answer = "state"

    def params(self, rnd, iid):
        return {"template": f"clicks-{iid}", "stream": f"clicks-{iid}-web", "future": f"clicks-{iid}-mobile",
                "existing_days": rnd.choice([7, 14, 30]), "new_days": rnd.choice([60, 90, 180])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/_index_template/{p['template']}", {
            "index_patterns": [f"clicks-{ctx.iid}-*"], "data_stream": {}, "priority": 500,
            "template": {"mappings": {"properties": {"@timestamp": {"type": "date"}, "page": {"type": "keyword"}}}}})
        es.put(f"/_data_stream/{p['stream']}")
        es.post(f"/{p['stream']}/_doc?refresh=true", {"@timestamp": "2026-10-20T10:00:00Z", "page": "/"})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The data stream `{p['stream']}` exists, created from the index template `{p['template']}`. It isn't
managed by ILM, and should stay that way: use the data stream lifecycle instead.

  1. Keep the data of `{p['stream']}` for {p['existing_days']} days.
  2. Data streams created from `{p['template']}` from now on (like a future `{p['future']}`) must
     keep their data for {p['new_days']} days.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _data_stream/{p['stream']}/_lifecycle
{{
  "data_retention": "{p['existing_days']}d"
}}

PUT _index_template/{p['template']}
{{
  "index_patterns": ["clicks-{ctx.iid}-*"],
  "data_stream": {{}},
  "priority": 500,
  "template": {{
    "mappings": {{
      "properties": {{
        "@timestamp": {{ "type": "date" }},
        "page": {{ "type": "keyword" }}
      }}
    }},
    "lifecycle": {{ "data_retention": "{p['new_days']}d" }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/_data_stream/{p['stream']}/_lifecycle")
        if c.check(status == 200, f"data stream {p['stream']} exists"):
            lifecycle = get(response, "data_streams.0.lifecycle", {})
            c.equal(lifecycle.get("data_retention"), f"{p['existing_days']}d",
                    f"{p['stream']} keeps data for {p['existing_days']} days")
            c.check(lifecycle.get("enabled", True), "its lifecycle is enabled")
        ds = es.send("GET", f"/_data_stream/{p['stream']}")[1] or {}
        c.check(not get(ds, "data_streams.0.ilm_policy"), f"{p['stream']} is not managed by ILM")
        sim = es.send("POST", f"/_index_template/_simulate_index/{p['future']}")[1] or {}
        c.equal(get(sim, "template.lifecycle.data_retention"), f"{p['new_days']}d",
                f"new data streams keep data for {p['new_days']} days")
