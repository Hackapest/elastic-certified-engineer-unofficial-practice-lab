from lib.tasklib import Task, get


class RolloverAlias(Task):
    id = "data-rollover-alias"
    title = "Time series without data streams: bootstrap index, rollover alias, ILM"
    covers = ["data.ilm.rollover-alias", "data.ilm.policy-in-template", "data.ilm.manual-rollover",
              "data.aliases.write-index", "data.templates.composable", "data.ilm.action.rollover"]
    answer = "state"

    def params(self, rnd, iid):
        name = rnd.choice(["audit", "payments", "events"])  # not "metrics": built-in metrics-*-* template
        return {"policy": f"{name}-rollover-{iid}", "alias": f"{name}-{iid}", "template": f"{name}-{iid}",
                "first": f"{name}-{iid}-000001", "second": f"{name}-{iid}-000002", "max_age": rnd.choice(["1d", "7d"])}

    def setup(self, ctx):
        p = ctx.p
        ctx.es.put(f"/_ilm/policy/{p['policy']}", {"policy": {"phases": {"hot": {"actions": {
            "rollover": {"max_age": p["max_age"], "max_primary_shard_size": "50gb"}}}}}})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The ILM policy `{p['policy']}` exists and rolls indices over. Use it for a time series that is
written through the alias `{p['alias']}`, without a data stream:

  1. Create an index template `{p['template']}` for indices named "{p['alias']}-*" that applies the policy
     and tells ILM which alias to roll over.
  2. Create the first index `{p['first']}` so that `{p['alias']}` points to it as the write index.
  3. Index one document through the alias, then roll the alias over by hand (don't wait for ILM),
     so that `{p['alias']}` writes to `{p['second']}`.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _index_template/{p['template']}
{{
  "index_patterns": ["{p['alias']}-*"],
  "priority": 500,
  "template": {{
    "settings": {{
      "index.lifecycle.name": "{p['policy']}",
      "index.lifecycle.rollover_alias": "{p['alias']}"
    }}
  }}
}}

PUT {p['first']}
{{
  "aliases": {{
    "{p['alias']}": {{ "is_write_index": true }}
  }}
}}

POST {p['alias']}/_doc?refresh=true
{{ "message": "first event" }}

POST {p['alias']}/_rollover
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        sim = es.send("POST", f"/_index_template/_simulate_index/{p['alias']}-000099")[1] or {}
        settings = get(sim, "template.settings.index.lifecycle", {})
        c.equal(settings.get("name"), p["policy"], f"new {p['alias']}-* indices get the policy")
        c.equal(settings.get("rollover_alias"), p["alias"], f"new {p['alias']}-* indices get the rollover alias")
        if not c.check(es.send("HEAD", f"/{p['first']}")[0] == 200, f"index {p['first']} exists"):
            return
        count = es.send("GET", f"/{p['first']}/_count")[1] or {}
        c.check((count.get("count") or 0) >= 1, f"a document was indexed into {p['first']}")
        c.check(es.send("HEAD", f"/{p['second']}")[0] == 200, f"the alias was rolled over to {p['second']}")
        aliases = es.send("GET", f"/_alias/{p['alias']}")[1] or {}
        writers = [i for i, a in aliases.items() if a.get("aliases", {}).get(p["alias"], {}).get("is_write_index")]
        c.equal(writers, [p["second"]], f"{p['alias']} writes to {p['second']}")
        c.check(p["first"] in aliases, f"{p['first']} is still readable through {p['alias']}")
        explain = es.get(f"/{p['second']}/_ilm/explain")["indices"].get(p["second"], {})
        c.check(explain.get("managed") and explain.get("policy") == p["policy"], f"{p['second']} is managed by ILM")
