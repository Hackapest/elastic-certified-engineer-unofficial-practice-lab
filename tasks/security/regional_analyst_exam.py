from lib.sampledata import CONTINENTS
from lib.tasklib import Task, get
from tasks.security._helpers import as_api_key, as_user, count, invalidate_keys, search, setup_orders, try_write

HIDDEN = ["email", "customer_phone", "customer_birth_date"]


class RegionalAnalystExam(Task):
    id = "security-regional-analyst-exam"
    title = "Exam-style: a role with document- and field-level security, a user and an API key"
    covers = ["security.rbac.roles", "security.rbac.document-level", "security.rbac.field-level",
              "security.rbac.native-users", "security.rbac.api-keys", "security.rbac.check-privileges"]
    size = "exam"
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"orders-secure-{iid}", "role": f"regional-analyst-{iid}", "user": f"analyst-{iid}",
                "password": f"Analyst-{iid}-pw", "key": f"dashboard-key-{iid}", "continent": rnd.choice(CONTINENTS),
                "docs": 1500}

    def setup(self, ctx):
        setup_orders(ctx.es, ctx.p["index"], ctx.p["docs"])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
An analyst may only see orders from {p['continent']} in the index `{p['index']}` on cluster A.

  1. Create the role `{p['role']}` that can read `{p['index']}`, but
       - only orders whose geoip.continent_name is "{p['continent']}"
       - without the fields {', '.join(HIDDEN)} (every other field stays visible)
     The analyst must also be able to create and manage their own API keys, and nothing else
     (no write access, no other indices, no other cluster privileges).
  2. Create the user `{p['user']}` with the password `{p['password']}` and only that role.
  3. As that user (not as elastic), create an API key named `{p['key']}` that expires in 30 days.
     A key created by a user can never see more than the user, so it inherits the restrictions.

Check the user's privileges with the has_privileges API before you hand it in.
"""

    def solution(self, ctx):
        p = ctx.p
        hidden = ", ".join(f'"{f}"' for f in HIDDEN)
        return f"""
POST _security/role/{p['role']}
{{
  "cluster": ["manage_own_api_key"],
  "indices": [
    {{
      "names": ["{p['index']}"],
      "privileges": ["read"],
      "query": {{ "term": {{ "geoip.continent_name": "{p['continent']}" }} }},
      "field_security": {{ "grant": ["*"], "except": [{hidden}] }}
    }}
  ]
}}

POST _security/user/{p['user']}
{{
  "password": "{p['password']}",
  "roles": ["{p['role']}"]
}}

# As the user, e.g. with curl -u {p['user']}:{p['password']} ... or in Kibana logged in as {p['user']}:
POST _security/api_key
{{
  "name": "{p['key']}",
  "expiration": "30d"
}}
"""

    def apply_solution(self, ctx):
        p, es = ctx.p, ctx.es
        es.post(f"/_security/role/{p['role']}", {"cluster": ["manage_own_api_key"], "indices": [{
            "names": [p["index"]], "privileges": ["read"],
            "query": {"term": {"geoip.continent_name": p["continent"]}},
            "field_security": {"grant": ["*"], "except": HIDDEN}}]})
        es.post(f"/_security/user/{p['user']}", {"password": p["password"], "roles": [p["role"]]})
        status, response = as_user("a", p["user"], p["password"]).send(
            "POST", "/_security/api_key", f'{{"name": "{p["key"]}", "expiration": "30d"}}'.encode(), "application/json")
        return None if status == 200 else str(response)[:300]

    def check_view(self, c, who, viewer, es, p):
        expected = es.post(f"/{p['index']}/_count", {"query": {"term": {"geoip.continent_name": p["continent"]}}})["count"]
        status, n = count(viewer, p["index"])
        c.check(status == 200 and n == expected, f"{who} sees exactly the {expected} orders from {p['continent']}",
                f"HTTP {status}, sees {n}")
        status, response = search(viewer, p["index"], size=20)
        sources = [h["_source"] for h in get(response, "hits.hits", [])]
        leaked = sorted({f for s in sources for f in HIDDEN if f in s})
        c.check(sources and not leaked and all("order_id" in s for s in sources),
                f"{who} sees the orders without {', '.join(HIDDEN)}",
                f"hidden fields visible: {leaked}" if leaked else f"HTTP {status}")

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        user = as_user("a", p["user"], p["password"])
        status, me = user.send("GET", "/_security/_authenticate")
        if not c.check(status == 200, f"{p['user']} can log in"):
            return
        c.equal(me.get("roles"), [p["role"]], f"{p['user']} has only the role {p['role']}")
        role = es.get(f"/_security/role/{p['role']}").get(p["role"], {})
        c.equal(sorted(role.get("cluster", [])), ["manage_own_api_key"],
                "the role's only cluster privilege lets the user manage their own API keys")
        self.check_view(c, p["user"], user, es, p)
        c.check(try_write(user, es, p["index"], {"order_id": "probe"}) == 403, f"{p['user']} can't write")
        c.check(search(user, "kibana_sample_data_flights", size=1)[0] == 403, f"{p['user']} can't read other indices")

        keys = es.get(f"/_security/api_key?name={p['key']}&active_only=true").get("api_keys", [])
        if not c.check(len(keys) == 1, f"there is one active API key {p['key']}", f"found {len(keys)}"):
            return
        key = keys[0]
        c.equal(key.get("username"), p["user"], f"the key belongs to {p['user']}")
        days = ((key.get("expiration") or 0) - key.get("creation", 0)) / 86400000
        c.check(29 <= days <= 31, "the key expires in 30 days", f"expires after {days:.1f} days")

    def cleanup(self, ctx):
        invalidate_keys(ctx.es, ctx.iid)
