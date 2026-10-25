import json

from lib.tasklib import Task
from tasks.security._helpers import as_user, count, err, send_json

PASSWORD = "reporting-pass-123"


class RolePrivileges(Task):
    id = "security-role-privileges"
    title = "A role with cluster and index privileges, assigned to a new user"
    covers = ["security.rbac.roles", "security.rbac.native-users", "security.rbac.check-privileges"]
    answer = "state"

    def params(self, rnd, iid):
        return {"role": f"reporting-{iid}", "user": f"reporter-{iid}", "pattern": f"reports-{iid}-*",
                "reports": [f"reports-{iid}-q{i}" for i in (1, 2)], "uploads": f"uploads-{iid}",
                "secret": f"payroll-{iid}", "append_only": rnd.random() < 0.5,
                "docs": [rnd.randint(5, 40), rnd.randint(5, 40)]}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for index, n in zip(p["reports"], p["docs"]):
            lines = "".join(json.dumps({"index": {}}) + "\n" + json.dumps({"n": i, "region": "eu"}) + "\n"
                            for i in range(n))
            es.send("POST", f"/{index}/_bulk?refresh=true", lines.encode(), "application/x-ndjson")
        for index in (p["uploads"], p["secret"]):
            es.put(f"/{index}/_doc/1?refresh=true", {"n": 0})

    def prompt(self, ctx):
        p = ctx.p
        uploads = ("may only add new documents to it: it must not be able to overwrite or delete existing "
                   "documents" if p["append_only"] else "may add, overwrite and delete documents in it")
        return f"""
Create the role `{p['role']}` on cluster A for a reporting tool:

  - It can read cluster health and stats (all read-only cluster monitoring APIs), but can't change
    anything at cluster level.
  - It can search all indices whose name matches `{p['pattern']}`, including ones created later, and
    read their mappings and settings. It can't write to them or delete them.
  - It can't search `{p['uploads']}`, but {uploads}.
  - It has no access to any other index.

Then create the user `{p['user']}` with the password `{PASSWORD}` and that role only. Use the has
privileges API (as the user, or the user privileges API) to check the result.
"""

    def solution(self, ctx):
        p = ctx.p
        privilege = "create_doc" if p["append_only"] else "write"
        return f"""
PUT _security/role/{p['role']}
{{
  "cluster": ["monitor"],
  "indices": [
    {{ "names": ["{p['pattern']}"], "privileges": ["read", "view_index_metadata"] }},
    {{ "names": ["{p['uploads']}"], "privileges": ["{privilege}"] }}
  ]
}}

PUT _security/user/{p['user']}
{{
  "password": "{PASSWORD}",
  "roles": ["{p['role']}"]
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        user = as_user("a", p["user"], PASSWORD)
        status, me = user.send("GET", "/_security/_authenticate")
        if not c.check(status == 200, f"{p['user']} can log in", err(status, me)):
            return
        c.equal(me.get("roles"), [p["role"]], f"{p['user']} has only the role {p['role']}")
        status, response = user.send("GET", "/_cluster/health")
        c.check(status == 200, f"{p['user']} can read cluster health", err(status, response))
        status, response = user.send("GET", "/_nodes/stats/jvm")
        c.check(status == 200, f"{p['user']} can read node stats", err(status, response))
        status, response = send_json(user, "POST", "/_security/user/_has_privileges", {
            "cluster": ["manage", "manage_security", "manage_ilm", "manage_index_templates"],
            "index": [{"names": [p["reports"][0], f"reports-{ctx.iid}-q9"],
                       "privileges": ["delete_index", "write", "manage"]},
                      {"names": [p["secret"], "kibana_sample_data_flights"], "privileges": ["read"]}]})
        if status == 200:
            granted = [k for k, v in response["cluster"].items() if v]
            granted += [f"{priv} on {name}" for name, privs in response["index"].items()
                        for priv, v in privs.items() if v]
            c.check(not granted, f"{p['user']} has no extra privileges", f"it can also: {', '.join(granted)}")
        else:
            c.fail(f"{p['user']} has no extra privileges", err(status, response))
        for index, n in zip(p["reports"], p["docs"]):
            status, got = count(user, index)
            c.check(status == 200 and got == n, f"{p['user']} can search {index}", f"HTTP {status}, {got} docs")
        status, got = count(user, p["pattern"])
        c.check(status == 200 and got == sum(p["docs"]), f"{p['user']} can search {p['pattern']}",
                f"HTTP {status}, {got} docs")
        status, response = user.send("GET", f"/{p['reports'][0]}/_mapping")
        c.check(status == 200, f"{p['user']} can read the mappings of {p['reports'][0]}", err(status, response))
        status, response = send_json(user, "PUT", f"/{p['reports'][0]}/_doc/x", {"n": -1})
        c.check(status == 403, f"{p['user']} can't write to {p['reports'][0]}", f"the write returned HTTP {status}")
        if status < 300:
            es.send("DELETE", f"/{p['reports'][0]}/_doc/x?refresh=true")
        status, _ = count(user, p["uploads"])
        c.check(status == 403, f"{p['user']} can't search {p['uploads']}", f"search returned HTTP {status}")
        status, response = send_json(user, "PUT", f"/{p['uploads']}/_create/new-{ctx.iid}", {"n": 1})
        c.check(status in (200, 201), f"{p['user']} can add documents to {p['uploads']}", err(status, response))
        es.send("DELETE", f"/{p['uploads']}/_doc/new-{ctx.iid}")
        status, _ = send_json(user, "PUT", f"/{p['uploads']}/_doc/1", {"n": 2})
        if p["append_only"]:
            c.check(status == 403, f"{p['user']} can't overwrite documents in {p['uploads']}",
                    f"overwriting returned HTTP {status}")
            es.put(f"/{p['uploads']}/_doc/1", {"n": 0})
            status, _ = user.send("DELETE", f"/{p['uploads']}/_doc/1")
            c.check(status == 403, f"{p['user']} can't delete documents in {p['uploads']}",
                    f"deleting returned HTTP {status}")
            es.put(f"/{p['uploads']}/_doc/1", {"n": 0})
        else:
            c.check(status in (200, 201), f"{p['user']} can overwrite documents in {p['uploads']}",
                    f"overwriting returned HTTP {status}")
            status, _ = user.send("DELETE", f"/{p['uploads']}/_doc/1")
            c.check(status == 200, f"{p['user']} can delete documents in {p['uploads']}",
                    f"deleting returned HTTP {status}")
            es.put(f"/{p['uploads']}/_doc/1", {"n": 0})
        status, _ = count(user, p["secret"])
        c.check(status == 403, f"{p['user']} can't search {p['secret']}", f"search returned HTTP {status}")
