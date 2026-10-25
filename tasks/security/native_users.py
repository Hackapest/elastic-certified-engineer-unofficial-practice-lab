from lib.tasklib import Task, get
from tasks.security._helpers import as_user, can_authenticate, count, err

FIRST_NAMES = ["Ada", "Grace", "Linus", "Margaret", "Ken", "Barbara", "Dennis", "Radia"]
LAST_NAMES = ["Lovelace", "Hopper", "Torvalds", "Hamilton", "Thompson", "Liskov", "Ritchie", "Perlman"]


class NativeUsers(Task):
    id = "security-native-users"
    title = "Create, update and disable native users and change a password"
    covers = ["security.rbac.native-users", "security.rbac.builtin"]
    answer = "state"

    def params(self, rnd, iid):
        first, last = rnd.choice(FIRST_NAMES), rnd.choice(LAST_NAMES)
        return {"user": f"{first.lower()}-{iid}", "full_name": f"{first} {last}",
                "email": f"{first.lower()}.{last.lower()}@example.com",
                "password": f"{rnd.choice(['blue', 'green', 'amber'])}-{rnd.randint(1000, 9999)}-pass",
                "ops": f"ops-{iid}", "ops_old": "ops-initial-pass",
                "ops_new": f"rotated-{rnd.randint(10000, 99999)}",
                "contractor": f"contractor-{iid}", "contractor_pw": "contractor-pass",
                "team": rnd.choice(["payments", "search", "platform", "analytics"])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/_security/user/{p['ops']}", {"password": p["ops_old"], "roles": ["viewer"]})
        es.put(f"/_security/user/{p['contractor']}", {"password": p["contractor_pw"], "roles": ["viewer"],
                                                       "full_name": "Temporary Contractor"})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Manage users in the native realm of cluster A.

  1. Create the user `{p['user']}` with the password `{p['password']}`, full name "{p['full_name']}",
     email {p['email']}, and the built-in role that gives read-only access to all data indices
     and to all of Kibana. Store the team "{p['team']}" in the user's metadata, under the key
     `team`.
  2. The user `{p['ops']}` must change its password to `{p['ops_new']}`. The old password must stop
     working.
  3. The user `{p['contractor']}` has left. Make sure the account can no longer log in, but keep it
     (don't delete it) for audit purposes.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _security/user/{p['user']}
{{
  "password": "{p['password']}",
  "full_name": "{p['full_name']}",
  "email": "{p['email']}",
  "roles": ["viewer"],
  "metadata": {{ "team": "{p['team']}" }}
}}

POST _security/user/{p['ops']}/_password
{{
  "password": "{p['ops_new']}"
}}

PUT _security/user/{p['contractor']}/_disable
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        ok, me = can_authenticate("a", p["user"], p["password"])
        if c.check(ok, f"{p['user']} can log in with the given password", err(0, me) if not ok else None):
            c.equal((me.get("full_name"), me.get("email")), (p["full_name"], p["email"]),
                    f"{p['user']} has the full name and email")
            c.equal(get(me, "metadata.team"), p["team"], f"{p['user']} has the team in its metadata")
            user = as_user("a", p["user"], p["password"])
            status, n = count(user, "kibana_sample_data_flights")
            c.check(status == 200 and n, f"{p['user']} can read data indices", f"search returned HTTP {status}")
            status, _ = user.send("POST", f"/kibana_sample_data_flights/_doc", b'{"x": 1}', "application/json")
            c.check(status == 403, f"{p['user']} can't write to data indices", f"the write returned HTTP {status}")
            app = as_user("a", p["user"], p["password"]).send("GET", "/_security/user/_privileges")[1] or {}
            kib = [a for a in app.get("applications", []) if a.get("application") == "kibana-.kibana"]
            c.check(any("read" in a.get("privileges", []) and "*" in a.get("resources", []) for a in kib),
                    f"{p['user']} has read-only access to all of Kibana",
                    "the user's roles grant no read privilege on all Kibana spaces")
        ok, _ = can_authenticate("a", p["ops"], p["ops_new"])
        c.check(ok, f"{p['ops']} can log in with the new password")
        ok, _ = can_authenticate("a", p["ops"], p["ops_old"])
        c.check(not ok, f"the old password of {p['ops']} no longer works")
        status, response = es.send("GET", f"/_security/user/{p['contractor']}")
        if c.check(status == 200, f"the user {p['contractor']} still exists"):
            c.check(response[p["contractor"]].get("enabled") is False, f"{p['contractor']} is disabled")
            ok, _ = can_authenticate("a", p["contractor"], p["contractor_pw"])
            c.check(not ok, f"{p['contractor']} can no longer log in")
