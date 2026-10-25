from lib import docker
from lib.tasklib import Task, get

REPO_ROOT = "/usr/share/elasticsearch/snapshots"


class IlmSnapshotPolicy(Task):
    id = "data-ilm-snapshot-policy"
    title = "Exam-style: snapshot repository, SLM policy, and an ILM policy with searchable snapshots"
    covers = ["data.ilm.action.searchable-snapshot", "data.ilm.action.wait-for-snapshot", "data.ilm.action.migrate",
              "data.ilm.action.allocate", "data.ilm.action.rollover", "data.ilm.action.delete",
              "data.ilm.create-policy"]
    size = "exam"
    answer = "state"

    def params(self, rnd, iid):
        hour, minute = rnd.choice([1, 2, 3, 4]), rnd.choice([0, 15, 30, 45])
        return {"repo": f"archive-repo-{iid}", "location": f"a/archive-{iid}", "slm": f"nightly-orders-{iid}",
                "policy": f"orders-{iid}", "hour": hour, "minute": minute, "keep": rnd.choice([14, 30, 60]),
                "warm": rnd.choice([3, 7]), "cold": rnd.choice([30, 60]), "delete": rnd.choice([180, 365]),
                "size": rnd.choice([10, 30, 50])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Orders are kept in rolling indices "orders-{ctx.iid}-*". Prepare their lifecycle on cluster A:

  1. Register a shared file system snapshot repository `{p['repo']}` at the location
     `{p['location']}` (relative to path.repo, which is already configured on all nodes).
  2. Create the snapshot lifecycle policy `{p['slm']}`: every day at {p['hour']:02d}:{p['minute']:02d}, snapshot
     the indices orders-{ctx.iid}-* into `{p['repo']}`, with snapshot names starting with "nightly-orders-"
     followed by the date; delete snapshots older than {p['keep']} days.
  3. Create the ILM policy `{p['policy']}`:
       hot     roll over at {p['size']}gb per primary shard
       warm    {p['warm']} days after rollover: do NOT use the automatic data tier migration; instead
               move the shards to nodes with the custom attribute temp=warm
       cold    {p['cold']} days after rollover: turn the index into a searchable snapshot stored in
               `{p['repo']}`
       delete  {p['delete']} days after rollover: delete the index, but only once the snapshot policy
               `{p['slm']}` has taken a snapshot after the index entered this phase
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _snapshot/{p['repo']}
{{
  "type": "fs",
  "settings": {{ "location": "{p['location']}" }}
}}

PUT _slm/policy/{p['slm']}
{{
  "schedule": "0 {p['minute']} {p['hour']} * * ?",
  "name": "<nightly-orders-{{now/d}}>",
  "repository": "{p['repo']}",
  "config": {{ "indices": ["orders-{ctx.iid}-*"] }},
  "retention": {{ "expire_after": "{p['keep']}d" }}
}}

PUT _ilm/policy/{p['policy']}
{{
  "policy": {{
    "phases": {{
      "hot": {{
        "actions": {{ "rollover": {{ "max_primary_shard_size": "{p['size']}gb" }} }}
      }},
      "warm": {{
        "min_age": "{p['warm']}d",
        "actions": {{
          "migrate": {{ "enabled": false }},
          "allocate": {{ "require": {{ "temp": "warm" }} }}
        }}
      }},
      "cold": {{
        "min_age": "{p['cold']}d",
        "actions": {{
          "searchable_snapshot": {{ "snapshot_repository": "{p['repo']}" }}
        }}
      }},
      "delete": {{
        "min_age": "{p['delete']}d",
        "actions": {{
          "wait_for_snapshot": {{ "policy": "{p['slm']}" }},
          "delete": {{}}
        }}
      }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, repo = es.send("GET", f"/_snapshot/{p['repo']}")
        if c.check(status == 200, f"repository {p['repo']} exists"):
            r = repo.get(p["repo"], {})
            location = get(r, "settings.location", "")
            c.check(r.get("type") == "fs" and location.rstrip("/") in (p["location"], f"{REPO_ROOT}/{p['location']}"),
                    f"it is an fs repository at {p['location']}", f"type {r.get('type')}, location {location}")
            status, response = es.send("POST", f"/_snapshot/{p['repo']}/_verify")
            c.check(status == 200, "the repository works on all nodes (verify API)", str(response)[:200])
        status, response = es.send("GET", f"/_slm/policy/{p['slm']}")
        if c.check(status == 200, f"snapshot lifecycle policy {p['slm']} exists"):
            s = get(response, f"{p['slm']}.policy", {})
            fields = s.get("schedule", "").split()
            c.check(len(fields) >= 6 and fields[0] == "0" and fields[1:3] == [str(p["minute"]), str(p["hour"])]
                    and fields[3] in ("*", "?") and fields[4] == "*" and fields[5] in ("*", "?"),
                    f"it runs every day at {p['hour']:02d}:{p['minute']:02d}", f"schedule: {s.get('schedule')}")
            name = s.get("name", "")
            c.check(name.startswith("<nightly-orders-{now") and name.endswith("}>"),
                    "snapshot names start with nightly-orders- followed by the date", f"name: {name}")
            c.equal(s.get("repository"), p["repo"], "it uses the repository")
            indices = get(s, "config.indices")
            c.check(indices in (f"orders-{ctx.iid}-*", [f"orders-{ctx.iid}-*"]), "it snapshots the orders indices",
                    f"indices: {indices}")
            c.equal(get(s, "retention.expire_after"), f"{p['keep']}d", f"snapshots expire after {p['keep']} days")
        status, response = es.send("GET", f"/_ilm/policy/{p['policy']}")
        if not c.check(status == 200, f"ILM policy {p['policy']} exists"):
            return
        phases = get(response, f"{p['policy']}.policy.phases", {})
        c.equal(get(phases, "hot.actions.rollover.max_primary_shard_size"), f"{p['size']}gb",
                f"hot: roll over at {p['size']}gb per primary shard")
        warm = phases.get("warm", {})
        c.equal(warm.get("min_age"), f"{p['warm']}d", f"warm starts {p['warm']} days after rollover")
        c.equal(get(warm, "actions.migrate.enabled"), False, "warm: data tier migration is disabled")
        c.equal(get(warm, "actions.allocate.require"), {"temp": "warm"}, "warm: shards move to temp=warm nodes")
        cold = phases.get("cold", {})
        c.equal((cold.get("min_age"), get(cold, "actions.searchable_snapshot.snapshot_repository")),
                (f"{p['cold']}d", p["repo"]), f"cold: searchable snapshot in {p['repo']} after {p['cold']} days")
        delete = phases.get("delete", {})
        c.equal((delete.get("min_age"), get(delete, "actions.wait_for_snapshot.policy"),
                 "delete" in delete.get("actions", {})), (f"{p['delete']}d", p["slm"], True),
                f"delete: wait for a snapshot of {p['slm']}, then delete after {p['delete']} days")

    def cleanup(self, ctx):
        # the generic cleanup unregisters the repository; its directory stays in the shared volume
        docker.compose("exec", "-T", "es-a1", "rm", "-rf", f"{REPO_ROOT}/{ctx.p['location']}", check=False,
                       capture=True)
