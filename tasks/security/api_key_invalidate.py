from lib.tasklib import Task, get
from tasks.security._helpers import api_keys, invalidate_keys, send_json

SERVICES = ["billing", "search", "reports", "export", "alerts", "mailer", "sync", "uploader"]
TEAMS = ["payments", "platform", "growth"]


class ApiKeyInvalidate(Task):
    id = "security-api-key-invalidate"
    title = "Find API keys with the query API and invalidate them"
    covers = ["security.rbac.api-keys"]
    answer = "state"

    def params(self, rnd, iid):
        services = rnd.sample(SERVICES, 7)
        team = rnd.choice(TEAMS)
        teams = [team, team, team] + [rnd.choice([t for t in TEAMS if t != team]) for _ in range(4)]
        rnd.shuffle(teams)
        keys = [{"name": f"{s}-{iid}", "team": t} for s, t in zip(services, teams)]
        legacy = rnd.choice([k for k in keys if k["team"] != team])
        return {"keys": keys, "team": team, "legacy": legacy["name"]}

    def setup(self, ctx):
        for key in ctx.p["keys"]:
            ctx.es.post("/_security/api_key", {"name": key["name"], "role_descriptors": {},
                                               "metadata": {"team": key["team"]}})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
A laptop of the {p['team']} team was stolen. The API keys of each team carry the team name in
their metadata (key `team`). On cluster A:

  1. Use the query API keys API to list the active API keys whose metadata team is
     "{p['team']}", and invalidate all of them.
  2. Also invalidate the API key named `{p['legacy']}`, which is no longer used.

All other API keys must stay active. (The keys of this task are named `*-{ctx.iid}`: leave keys of
other tasks alone.)
"""

    def solution(self, ctx):
        p = ctx.p
        by_name = "\n\n".join(f'DELETE _security/api_key\n{{\n  "name": "{k["name"]}"\n}}'
                              for k in p["keys"] if k["team"] == p["team"])
        return f"""
GET _security/_query/api_key
{{
  "query": {{
    "bool": {{
      "filter": [
        {{ "term": {{ "metadata.team": "{p['team']}" }} }},
        {{ "term": {{ "invalidated": false }} }},
        {{ "wildcard": {{ "name": "*-{ctx.iid}" }} }}
      ]
    }}
  }}
}}

# Invalidate them with the IDs from the response:
#   DELETE _security/api_key
#   {{ "ids": ["<id 1>", "<id 2>", "<id 3>"] }}
# or one by one by name:
{by_name}

DELETE _security/api_key
{{
  "name": "{p['legacy']}"
}}
"""

    def verify(self, ctx, c):
        p = ctx.p
        state = {k["name"]: k.get("invalidated") for k in api_keys(ctx.es, f"*{ctx.iid}*")}
        leaked = [k["name"] for k in p["keys"] if k["team"] == p["team"]]
        still = [n for n in leaked if state.get(n) is False]
        c.check(not still, f"all API keys of the {p['team']} team are invalidated", f"still active: {still}")
        c.check(state.get(p["legacy"]) is True, f"the API key {p['legacy']} is invalidated")
        keep = [k["name"] for k in p["keys"] if k["team"] != p["team"] and k["name"] != p["legacy"]]
        gone = [n for n in keep if state.get(n) is not False]
        c.check(not gone, "the other API keys are still active", f"invalidated or missing: {gone}")

    def cleanup(self, ctx):
        invalidate_keys(ctx.es, ctx.iid)
