from lib.tasklib import Task, get


def simulate(es, index):
    status, response = es.send("POST", f"/_index_template/_simulate_index/{index}")
    return response.get("template") if status == 200 else None


class TemplatePriority(Task):
    id = "data-template-priority"
    title = "Override an existing index template for a subset of indices"
    covers = ["data.templates.priority", "data.templates.composable", "data.templates.simulate"]
    answer = "state"

    def params(self, rnd, iid):
        sub = rnd.choice(["audit", "security", "billing"])
        return {"base": f"app-base-{iid}", "new": f"app-{sub}-{iid}", "prefix": f"app-{iid}-",
                "sub": sub, "replicas": rnd.choice([0, 2]),
                "refresh": rnd.choice(["10s", "30s"]), "base_priority": rnd.choice([100, 200])}

    def setup(self, ctx):
        p = ctx.p
        ctx.es.put(f"/_index_template/{p['base']}", {
            "index_patterns": [f"{p['prefix']}*"], "priority": p["base_priority"],
            "template": {"settings": {"number_of_replicas": 1},
                         "mappings": {"properties": {"message": {"type": "text"},
                                                     "@timestamp": {"type": "date"},
                                                     "service": {"type": "keyword"}}}}})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index template `{p['base']}` applies to all indices starting with "{p['prefix']}". Look at it.

Indices starting with "{p['prefix']}{p['sub']}-" need different settings: {p['replicas']} replica(s), a refresh
interval of {p['refresh']}, and an extra keyword field `user`. Create a new index template `{p['new']}` for
them. They must keep all the fields of `{p['base']}`. Don't change `{p['base']}`; other "{p['prefix']}" indices
must stay as they are.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _index_template/{p['new']}
{{
  "index_patterns": ["{p['prefix']}{p['sub']}-*"],
  "priority": {p['base_priority'] + 10},
  "template": {{
    "settings": {{ "number_of_replicas": {p['replicas']}, "refresh_interval": "{p['refresh']}" }},
    "mappings": {{
      "properties": {{
        "message": {{ "type": "text" }},
        "@timestamp": {{ "type": "date" }},
        "service": {{ "type": "keyword" }},
        "user": {{ "type": "keyword" }}
      }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        c.check(es.send("GET", f"/_index_template/{p['new']}")[0] == 200, f"index template {p['new']} exists")
        sim = simulate(es, f"{p['prefix']}{p['sub']}-2026.10")
        if not c.check(sim, f"a new {p['prefix']}{p['sub']}- index matches a template"):
            return
        c.equal(get(sim, "settings.index.number_of_replicas"), str(p["replicas"]), "it gets the new replicas")
        c.equal(get(sim, "settings.index.refresh_interval"), p["refresh"], "it gets the new refresh interval")
        types = {k: v.get("type") for k, v in get(sim, "mappings.properties", {}).items()}
        c.equal(types, {"message": "text", "@timestamp": "date", "service": "keyword", "user": "keyword"},
                "it gets the base fields plus user")
        base = simulate(es, f"{p['prefix']}orders-2026.10")
        c.equal(get(base, "settings.index.number_of_replicas"), "1", "other indices still get the base template")
        status, response = es.send("GET", f"/_index_template/{p['base']}")
        t = get(response, "index_templates.0.index_template", {})
        c.check(status == 200 and t.get("priority") == p["base_priority"] and
                get(t, "template.settings.index.number_of_replicas") == "1",
                f"{p['base']} is unchanged")
