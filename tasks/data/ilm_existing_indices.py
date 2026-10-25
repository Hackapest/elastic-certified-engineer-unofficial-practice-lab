from lib.tasklib import Task, get, index_settings


class IlmExistingIndices(Task):
    id = "data-ilm-existing-indices"
    title = "Put existing indices under ILM, switch a policy and move an index to the next phase"
    covers = ["data.ilm.apply-existing", "data.ilm.update-switch", "data.ilm.move-retry", "data.ilm.explain",
              "data.ilm.create-policy", "data.ilm.action.readonly", "data.ilm.action.set-priority"]
    answer = "state"

    def params(self, rnd, iid):
        year = rnd.choice([2023, 2024, 2025])
        months = rnd.sample(range(1, 13), 3)
        months.sort()
        return {"policy": f"invoices-{iid}", "legacy": f"invoices-legacy-{iid}",
                "indices": [f"invoices-{iid}-{year}.{m:02d}" for m in months],
                "warm": rnd.choice([30, 60, 90]), "delete": rnd.choice([365, 730])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/_ilm/policy/{p['legacy']}", {"policy": {"phases": {
            "hot": {"actions": {}}, "delete": {"min_age": "7d", "actions": {"delete": {}}}}}})
        for i, index in enumerate(p["indices"]):
            settings = {"number_of_shards": 1, "number_of_replicas": 0}
            if i == 2:
                settings["index.lifecycle.name"] = p["legacy"]
            es.put(f"/{index}", {"settings": settings})
            es.post(f"/{index}/_doc?refresh=true", {"invoice": f"INV-{i}", "amount": 100 + i})

    def prompt(self, ctx):
        p = ctx.p
        first, second, third = p["indices"]
        return f"""
Monthly invoice indices already exist: `{first}`, `{second}` and `{third}`.
The first two are not managed by ILM; `{third}` uses the policy `{p['legacy']}`, which would delete it
after a week.

  1. Create the ILM policy `{p['policy']}`:
       hot     index priority 100
       warm    {p['warm']} days after index creation: index priority 50, make the index read-only
       delete  {p['delete']} days after index creation
  2. Put `{first}` and `{second}` under this policy (they are existing indices; no template change needed).
  3. Switch `{third}` from `{p['legacy']}` to `{p['policy']}`. Don't delete `{p['legacy']}`.
  4. `{first}` is already old: move it into the warm phase now, without waiting {p['warm']} days and
     without changing the policy.

Use the ILM explain API to check the phase each index is in.
"""

    def solution(self, ctx):
        p = ctx.p
        first, second, third = p["indices"]
        return f"""
PUT _ilm/policy/{p['policy']}
{{
  "policy": {{
    "phases": {{
      "hot": {{
        "actions": {{ "set_priority": {{ "priority": 100 }} }}
      }},
      "warm": {{
        "min_age": "{p['warm']}d",
        "actions": {{
          "set_priority": {{ "priority": 50 }},
          "readonly": {{}}
        }}
      }},
      "delete": {{
        "min_age": "{p['delete']}d",
        "actions": {{ "delete": {{}} }}
      }}
    }}
  }}
}}

PUT {first},{second}/_settings
{{
  "index.lifecycle.name": "{p['policy']}"
}}

POST {third}/_ilm/remove

PUT {third}/_settings
{{
  "index.lifecycle.name": "{p['policy']}"
}}

# wait until ILM has run the first steps, then check where the index is
GET _cluster/health/{first}?wait_for_events=languid

GET {first}/_ilm/explain

POST _ilm/move/{first}
{{
  "current_step": {{ "phase": "hot", "action": "complete", "name": "complete" }},
  "next_step": {{ "phase": "warm" }}
}}

GET invoices-{ctx.iid}-*/_ilm/explain
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        first, second, third = p["indices"]
        status, response = es.send("GET", f"/_ilm/policy/{p['policy']}")
        if c.check(status == 200, f"policy {p['policy']} exists"):
            phases = get(response, f"{p['policy']}.policy.phases", {})
            c.equal(get(phases, "hot.actions.set_priority.priority"), 100, "hot: priority 100")
            warm = phases.get("warm", {})
            c.equal((warm.get("min_age"), get(warm, "actions.set_priority.priority"), "readonly" in warm.get("actions", {})),
                    (f"{p['warm']}d", 50, True), f"warm after {p['warm']} days: priority 50 and read-only")
            c.equal((get(phases, "delete.min_age"), "delete" in get(phases, "delete.actions", {})),
                    (f"{p['delete']}d", True), f"delete after {p['delete']} days")
        c.check(es.send("GET", f"/_ilm/policy/{p['legacy']}")[0] == 200, f"policy {p['legacy']} still exists")
        explain = get(es.send("GET", f"/invoices-{ctx.iid}-*/_ilm/explain")[1] or {}, "indices", {})
        for index in p["indices"]:
            s = index_settings(es, index) or {}
            c.equal(s.get("index.lifecycle.name"), p["policy"], f"{index} is managed by {p['policy']}")
            e = explain.get(index, {})
            c.check(e.get("policy") == p["policy"] and e.get("managed"),
                    f"ILM explain shows {index} managed by {p['policy']}", str(explain.get(index))[:200])
        # index names contain dots, so no dotted get() here
        c.equal(explain.get(first, {}).get("phase"), "warm", f"{first} is in the warm phase")
        phase = explain.get(second, {}).get("phase")
        c.check(phase in ("new", "hot"), f"{second} is still in the hot phase", f"phase: {phase}")
