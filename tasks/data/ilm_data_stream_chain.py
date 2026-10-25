import json

from lib.tasklib import Task, get


class IlmDataStreamChain(Task):
    id = "data-ilm-data-stream-chain"
    title = "Exam-style: lifecycle policy, component templates and a data stream together"
    covers = ["data.ilm.tutorial-data-streams", "data.ilm.policy-in-template", "data.ilm.create-policy",
              "data.ilm.explain", "data.templates.data-stream-template", "data.templates.component",
              "data.templates.use-data-stream", "data.ilm.action.rollover", "data.ilm.action.delete",
              "data.aliases.data-stream-alias"]
    size = "exam"
    answer = "state"

    def params(self, rnd, iid):
        return {"policy": f"weblogs-policy-{iid}", "mappings": f"weblogs-mappings-{iid}",
                "template": f"weblogs-{iid}", "stream": f"weblogs-{iid}-prod", "alias": f"all-weblogs-{iid}",
                "docs": rnd.choice([2, 5, 10]) * 1000, "days": rnd.choice([7, 30, 90]),
                "status_type": rnd.choice(["short", "integer"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Web server logs go to data streams named "weblogs-{ctx.iid}-<environment>". Set this up:

  1. An ILM policy `{p['policy']}`: roll over when a primary shard reaches {p['docs']} documents or
     1 day, and delete the data {p['days']} days after rollover.
  2. A component template `{p['mappings']}` with the mapping: @timestamp (date), url (keyword),
     status ({p['status_type']}), bytes (long).
  3. An index template `{p['template']}` for those data streams, that uses the component template
     and the policy, with 1 replica.
  4. Create the data stream `{p['stream']}`, add one document to it, and make it searchable through
     the alias `{p['alias']}`.

Check with the ILM explain API that the backing index is managed by the policy.
"""

    def solution(self, ctx):
        p = ctx.p
        doc = json.dumps({"@timestamp": "2026-10-20T12:00:00Z", "url": "/", "status": 200, "bytes": 512})
        return f"""
PUT _ilm/policy/{p['policy']}
{{
  "policy": {{
    "phases": {{
      "hot": {{
        "actions": {{
          "rollover": {{ "max_primary_shard_docs": {p['docs']}, "max_age": "1d" }}
        }}
      }},
      "delete": {{
        "min_age": "{p['days']}d",
        "actions": {{ "delete": {{}} }}
      }}
    }}
  }}
}}

PUT _component_template/{p['mappings']}
{{
  "template": {{
    "mappings": {{
      "properties": {{
        "@timestamp": {{ "type": "date" }},
        "url": {{ "type": "keyword" }},
        "status": {{ "type": "{p['status_type']}" }},
        "bytes": {{ "type": "long" }}
      }}
    }}
  }}
}}

PUT _index_template/{p['template']}
{{
  "index_patterns": ["weblogs-{ctx.iid}-*"],
  "data_stream": {{}},
  "priority": 500,
  "composed_of": ["{p['mappings']}"],
  "template": {{
    "settings": {{
      "index.lifecycle.name": "{p['policy']}",
      "number_of_replicas": 1
    }}
  }}
}}

PUT _data_stream/{p['stream']}

POST {p['stream']}/_doc?refresh=true
{doc}

POST _aliases
{{
  "actions": [
    {{ "add": {{ "index": "{p['stream']}", "alias": "{p['alias']}" }} }}
  ]
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/_ilm/policy/{p['policy']}")
        if c.check(status == 200, f"policy {p['policy']} exists"):
            phases = get(response, f"{p['policy']}.policy.phases", {})
            rollover = get(phases, "hot.actions.rollover", {})
            c.equal((rollover.get("max_primary_shard_docs"), rollover.get("max_age")), (p["docs"], "1d"),
                    "the policy rolls over on primary shard documents or 1 day")
            c.equal((get(phases, "delete.min_age"), "delete" in get(phases, "delete.actions", {})),
                    (f"{p['days']}d", True), f"the policy deletes after {p['days']} days")
        status, response = es.send("GET", f"/_component_template/{p['mappings']}")
        if c.check(status == 200, f"component template {p['mappings']} exists"):
            props = get(response, "component_templates.0.component_template.template.mappings.properties", {})
            c.equal({k: v.get("type") for k, v in props.items()},
                    {"@timestamp": "date", "url": "keyword", "status": p["status_type"], "bytes": "long"},
                    "the component template has the mapping")
        status, response = es.send("GET", f"/_index_template/{p['template']}")
        if c.check(status == 200, f"index template {p['template']} exists"):
            t = get(response, "index_templates.0.index_template", {})
            c.check("data_stream" in t, "the index template creates data streams")
            c.check(p["mappings"] in t.get("composed_of", []), "the index template uses the component template")
        sim = es.send("POST", f"/_index_template/_simulate_index/weblogs-{ctx.iid}-staging")[1] or {}
        c.equal(get(sim, "template.settings.index.lifecycle.name"), p["policy"],
                "new weblogs data streams use the policy")
        c.equal(get(sim, "template.settings.index.number_of_replicas"), "1", "new weblogs data streams get 1 replica")
        status, response = es.send("GET", f"/_data_stream/{p['stream']}")
        if not c.check(status == 200, f"data stream {p['stream']} exists"):
            return
        ds = response["data_streams"][0]
        c.equal(ds.get("ilm_policy"), p["policy"], "the data stream is managed by the policy")
        write_index = ds["indices"][-1]["index_name"]
        explain = es.get(f"/{write_index}/_ilm/explain")["indices"][write_index]
        c.check(explain.get("managed") and explain.get("policy") == p["policy"],
                "ILM explain shows the backing index managed by the policy")
        count = es.send("GET", f"/{p['alias']}/_count")[1] or {}
        c.check((count.get("count") or 0) >= 1, f"the data is searchable through {p['alias']}",
                str(count)[:200])
