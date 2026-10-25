from lib.tasklib import Task, get


class IlmPolicy(Task):
    id = "data-ilm-policy"
    title = "Write an ILM policy with hot, warm, cold and delete phases"
    covers = ["data.ilm.create-policy", "data.ilm.action.rollover", "data.ilm.action.shrink",
              "data.ilm.action.forcemerge", "data.ilm.action.allocate", "data.ilm.action.set-priority",
              "data.ilm.action.readonly", "data.ilm.action.delete", "data.ilm.ilm-overview"]
    answer = "state"

    def params(self, rnd, iid):
        warm = rnd.choice([3, 7, 14])
        cold = warm + rnd.choice([14, 23, 30])
        return {"policy": f"timeseries-{iid}", "size": rnd.choice([10, 25, 50]), "age": rnd.choice([1, 7]),
                "warm": warm, "cold": cold, "delete": cold + rnd.choice([30, 60, 335]),
                "attr": rnd.choice([("temp", "warm"), ("zone", "zone-3")])}

    def prompt(self, ctx):
        p = ctx.p
        attr, value = p["attr"]
        return f"""
Create the ILM policy `{p['policy']}`:

  hot     roll over when a primary shard reaches {p['size']}gb or the index is {p['age']} day(s) old,
          whichever comes first; recovery priority 100
  warm    {p['warm']} days after rollover: shrink to 1 primary shard, force-merge to 1 segment,
          move to nodes with the attribute {attr}={value}, keep 1 replica; recovery priority 50
  cold    {p['cold']} days after rollover: make the index read-only, recovery priority 0
  delete  {p['delete']} days after rollover: delete the index
"""

    def solution(self, ctx):
        p = ctx.p
        attr, value = p["attr"]
        return f"""
PUT _ilm/policy/{p['policy']}
{{
  "policy": {{
    "phases": {{
      "hot": {{
        "actions": {{
          "rollover": {{ "max_primary_shard_size": "{p['size']}gb", "max_age": "{p['age']}d" }},
          "set_priority": {{ "priority": 100 }}
        }}
      }},
      "warm": {{
        "min_age": "{p['warm']}d",
        "actions": {{
          "shrink": {{ "number_of_shards": 1 }},
          "forcemerge": {{ "max_num_segments": 1 }},
          "allocate": {{ "number_of_replicas": 1, "require": {{ "{attr}": "{value}" }} }},
          "set_priority": {{ "priority": 50 }}
        }}
      }},
      "cold": {{
        "min_age": "{p['cold']}d",
        "actions": {{
          "readonly": {{}},
          "set_priority": {{ "priority": 0 }}
        }}
      }},
      "delete": {{
        "min_age": "{p['delete']}d",
        "actions": {{ "delete": {{}} }}
      }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        attr, value = p["attr"]
        status, response = es.send("GET", f"/_ilm/policy/{p['policy']}")
        if not c.check(status == 200, f"policy {p['policy']} exists"):
            return
        phases = get(response, f"{p['policy']}.policy.phases", {})
        hot, warm = get(phases, "hot.actions", {}), get(phases, "warm.actions", {})
        cold, delete = get(phases, "cold.actions", {}), phases.get("delete", {})
        rollover = hot.get("rollover", {})
        c.equal((rollover.get("max_primary_shard_size"), rollover.get("max_age")), (f"{p['size']}gb", f"{p['age']}d"),
                "hot: rollover on primary shard size or age")
        c.equal(get(hot, "set_priority.priority"), 100, "hot: priority 100")
        c.equal(get(phases, "warm.min_age"), f"{p['warm']}d", f"warm starts after {p['warm']} days")
        c.equal(get(warm, "shrink.number_of_shards"), 1, "warm: shrink to 1 shard")
        c.equal(get(warm, "forcemerge.max_num_segments"), 1, "warm: force-merge to 1 segment")
        allocate = warm.get("allocate", {})
        c.equal((get(allocate, f"require.{attr}"), allocate.get("number_of_replicas")), (value, 1),
                f"warm: allocate to {attr}={value} with 1 replica")
        c.equal(get(warm, "set_priority.priority"), 50, "warm: priority 50")
        c.equal(get(phases, "cold.min_age"), f"{p['cold']}d", f"cold starts after {p['cold']} days")
        c.check("readonly" in cold, "cold: read-only")
        c.equal(get(cold, "set_priority.priority"), 0, "cold: priority 0")
        c.equal((delete.get("min_age"), "delete" in delete.get("actions", {})), (f"{p['delete']}d", True),
                f"delete after {p['delete']} days")
