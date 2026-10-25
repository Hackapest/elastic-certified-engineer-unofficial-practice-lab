from lib.tasklib import Task, get


def simulate(es, index):
    status, response = es.send("POST", f"/_index_template/_simulate_index/{index}")
    return response.get("template") if status == 200 else None


class ComponentTemplates(Task):
    id = "data-component-templates"
    title = "Compose an index template from component templates"
    covers = ["data.templates.composable", "data.templates.component", "data.templates.simulate",
              "data.templates.template-defaults", "ingest.mapping.explicit"]
    answer = "state"

    def params(self, rnd, iid):
        return {"settings": f"sensor-settings-{iid}", "mappings": f"sensor-mappings-{iid}",
                "template": f"sensor-template-{iid}", "pattern": f"sensor-{iid}-*", "alias": f"sensors-{iid}",
                "shards": rnd.choice([1, 2, 3]), "replicas": rnd.choice([0, 1]), "priority": rnd.choice([150, 300, 500]),
                "value_type": rnd.choice(["float", "double", "scaled_float"])}

    def prompt(self, ctx):
        p = ctx.p
        value = "a scaled float with scaling factor 100" if p["value_type"] == "scaled_float" else p["value_type"]
        return f"""
Create two component templates:

  {p['settings']:<28} {p['shards']} primary shard(s), {p['replicas']} replica(s)
  {p['mappings']:<28} @timestamp (date), sensor_id (keyword), value ({value})

and an index template `{p['template']}` with priority {p['priority']} that is built from both and applies
to every index whose name starts with "sensor-{ctx.iid}-". Every such index must also be reachable
through the alias `{p['alias']}`.

Check the result with the simulate index API before you hand it in.
"""

    def solution(self, ctx):
        p = ctx.p
        value = '{ "type": "scaled_float", "scaling_factor": 100 }' if p["value_type"] == "scaled_float" \
            else f'{{ "type": "{p["value_type"]}" }}'
        return f"""
PUT _component_template/{p['settings']}
{{
  "template": {{
    "settings": {{ "number_of_shards": {p['shards']}, "number_of_replicas": {p['replicas']} }}
  }}
}}

PUT _component_template/{p['mappings']}
{{
  "template": {{
    "mappings": {{
      "properties": {{
        "@timestamp": {{ "type": "date" }},
        "sensor_id": {{ "type": "keyword" }},
        "value": {value}
      }}
    }}
  }}
}}

PUT _index_template/{p['template']}
{{
  "index_patterns": ["{p['pattern']}"],
  "priority": {p['priority']},
  "composed_of": ["{p['settings']}", "{p['mappings']}"],
  "template": {{
    "aliases": {{ "{p['alias']}": {{}} }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        for name in (p["settings"], p["mappings"]):
            c.check(es.send("GET", f"/_component_template/{name}")[0] == 200, f"component template {name} exists")
        status, response = es.send("GET", f"/_index_template/{p['template']}")
        if not c.check(status == 200, f"index template {p['template']} exists"):
            return
        t = response["index_templates"][0]["index_template"]
        c.equal(t.get("priority"), p["priority"], "priority")
        c.equal(sorted(t.get("composed_of", [])), sorted([p["settings"], p["mappings"]]),
                "it is composed of both component templates")
        sim = simulate(es, f"sensor-{ctx.iid}-2026.10")
        if not c.check(sim, f"a new index sensor-{ctx.iid}-2026.10 matches it"):
            return
        c.equal(get(sim, "settings.index.number_of_shards"), str(p["shards"]), "new indices get the shards")
        c.equal(get(sim, "settings.index.number_of_replicas"), str(p["replicas"]), "new indices get the replicas")
        props = get(sim, "mappings.properties", {})
        c.equal({k: v.get("type") for k, v in props.items()},
                {"@timestamp": "date", "sensor_id": "keyword", "value": p["value_type"]}, "new indices get the mapping")
        c.check(p["alias"] in (sim.get("aliases") or {}), f"new indices get the alias {p['alias']}")
        other = simulate(es, f"sensors-{ctx.iid}-x")
        c.check(not other or p["alias"] not in (other.get("aliases") or {}),
                "other index names don't match the template")
