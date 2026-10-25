from lib.tasklib import Task, get
from tasks.security._helpers import as_user, count, err

PASSWORD = "runas-pass-123"


class RunAs(Task):
    id = "security-run-as"
    title = "Let a support user submit requests on behalf of other users (run_as)"
    covers = ["security.rbac.run-as", "security.rbac.roles", "security.rbac.check-privileges"]
    answer = "state"

    def params(self, rnd, iid):
        team = rnd.choice(["finance", "hr", "legal", "sales"])
        return {"index": f"{team}-docs-{iid}", "targets": [f"{team}-{n}-{iid}" for n in rnd.sample(
                    ["alice", "bob", "carol", "dave", "erin"], 2)],
                "other": f"admin-{rnd.choice(['ops', 'sec'])}-{iid}", "team_role": f"{team}-reader-{iid}",
                "role": f"impersonator-{iid}", "user": f"helpdesk-{iid}", "team": team,
                "docs": rnd.randint(3, 30)}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for i in range(p["docs"]):
            es.post(f"/{p['index']}/_doc", {"n": i})
        es.post(f"/{p['index']}/_refresh")
        es.put(f"/_security/role/{p['team_role']}", {"indices": [{"names": [p["index"]], "privileges": ["read"]}]})
        for user in p["targets"]:
            es.put(f"/_security/user/{user}", {"password": "target-pass-123", "roles": [p["team_role"]]})
        es.put(f"/_security/user/{p['other']}", {"password": "target-pass-123", "roles": ["superuser"]})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The helpdesk reproduces problems that users of the {p['team']} team report. On cluster A:

  1. Create the role `{p['role']}` that lets its holder submit requests on behalf of the users
     `{p['targets'][0]}` and `{p['targets'][1]}`, and of no other user. The role grants no index or cluster
     privileges of its own.
  2. Create the user `{p['user']}` (password `{PASSWORD}`) with only that role.
  3. Check it: as `{p['user']}`, call the authenticate API on behalf of `{p['targets'][0]}`, then search
     `{p['index']}` on behalf of that user.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _security/role/{p['role']}
{{
  "run_as": ["{p['targets'][0]}", "{p['targets'][1]}"]
}}

PUT _security/user/{p['user']}
{{
  "password": "{PASSWORD}",
  "roles": ["{p['role']}"]
}}

# The check, with curl (Dev Tools always runs as the logged-in user):
#   curl --cacert .state/ca.crt -u {p['user']}:{PASSWORD} -H "es-security-runas-user: {p['targets'][0]}" \\
#     "https://localhost:9200/_security/_authenticate?pretty"
#   curl --cacert .state/ca.crt -u {p['user']}:{PASSWORD} -H "es-security-runas-user: {p['targets'][0]}" \\
#     "https://localhost:9200/{p['index']}/_search?pretty"
"""

    def verify(self, ctx, c):
        p = ctx.p
        user = as_user("a", p["user"], PASSWORD)
        status, me = user.send("GET", "/_security/_authenticate")
        if not c.check(status == 200, f"{p['user']} can log in", err(status, me)):
            return
        c.equal(me.get("roles"), [p["role"]], f"{p['user']} has only the role {p['role']}")
        for target in p["targets"]:
            runas = as_user("a", p["user"], PASSWORD, {"es-security-runas-user": target})
            status, response = runas.send("GET", "/_security/_authenticate")
            c.check(status == 200 and response.get("username") == target
                    and get(response, "authentication_realm.name") == "default_native",
                    f"{p['user']} can run as {target}", err(status, response))
            status, got = count(runas, p["index"])
            c.check(status == 200 and got == p["docs"], f"running as {target}, {p['user']} can search {p['index']}",
                    f"HTTP {status}, {got} documents")
        runas = as_user("a", p["user"], PASSWORD, {"es-security-runas-user": p["other"]})
        status, _ = runas.send("GET", "/_security/_authenticate")
        c.check(status == 403, f"{p['user']} can't run as {p['other']}", f"run as returned HTTP {status}")
        status, _ = count(user, p["index"])
        c.check(status == 403, f"{p['user']} can't search {p['index']} as itself", f"search returned HTTP {status}")
