from lib.sampledata import CONTINENTS
from lib.tasklib import Task
from tasks.security._helpers import as_user, count, err, send_json, setup_orders

DOCS = 2000
PASSWORD = "region-pass-123"


class TemplatedDls(Task):
    id = "security-templated-dls"
    title = "One role for every region: templated document-level security with user metadata"
    covers = ["security.rbac.templated-dls", "security.rbac.document-level", "security.rbac.native-users"]
    answer = "state"

    def params(self, rnd, iid):
        a, b, probe = rnd.sample(CONTINENTS, 3)
        key = rnd.choice(["region", "continent", "sales_area"])
        return {"index": f"orders-{iid}", "role": f"regional-sales-{iid}", "key": key,
                "users": {f"sales-{a.split()[0].lower()}-{iid}": a, f"sales-{b.split()[0].lower()}-{iid}": b},
                "probe_user": f"probe-{iid}", "probe": probe}

    def setup(self, ctx):
        setup_orders(ctx.es, ctx.p["index"], DOCS)

    def prompt(self, ctx):
        p = ctx.p
        users = "\n".join(f"       - `{u}` (password `{PASSWORD}`), region {r}" for u, r in p["users"].items())
        return f"""
Regional sales managers may only see the orders of their own region in `{p['index']}` on
cluster A. The region of an order is in the field geoip.continent_name.

  1. Create a single role `{p['role']}` for all managers. It grants read access to `{p['index']}`,
     limited to the orders of the user's region. The region is not written in the role: it is
     read from the user's metadata, key `{p['key']}`, so a new manager only needs a user with that
     metadata.
  2. Create these users with that role, and their region in their metadata:
{users}
"""

    def solution(self, ctx):
        p = ctx.p
        users = "\n".join(f"""
PUT _security/user/{u}
{{
  "password": "{PASSWORD}",
  "roles": ["{p['role']}"],
  "metadata": {{ "{p['key']}": "{r}" }}
}}""" for u, r in p["users"].items())
        return f"""
PUT _security/role/{p['role']}
{{
  "indices": [
    {{
      "names": ["{p['index']}"],
      "privileges": ["read"],
      "query": {{
        "template": {{
          "source": {{
            "term": {{ "geoip.continent_name": "{{{{_user.metadata.{p['key']}}}}}" }}
          }}
        }}
      }}
    }}
  ]
}}
{users}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es

        def sees_region(user, password, region):
            want = count(es, p["index"], {"term": {"geoip.continent_name": region}})[1]
            status, got = count(as_user("a", user, password), p["index"])
            return c.check(status == 200 and got == want, f"{user} sees only the {want} orders from {region}",
                           f"HTTP {status}, sees {got} orders" if status == 200 else f"HTTP {status}")

        for user, region in p["users"].items():
            status, response = es.send("GET", f"/_security/user/{user}")
            if c.check(status == 200, f"user {user} exists"):
                sees_region(user, PASSWORD, region)
        # A new manager: only a user with the role and metadata, no role change
        status, _ = send_json(es, "PUT", f"/_security/user/{p['probe_user']}",
                              {"password": PASSWORD, "roles": [p["role"]], "metadata": {p["key"]: p["probe"]}})
        if status == 200:
            want = count(es, p["index"], {"term": {"geoip.continent_name": p["probe"]}})[1]
            status, got = count(as_user("a", p["probe_user"], PASSWORD), p["index"])
            c.check(status == 200 and got == want,
                    f"a new user with {p['key']}: {p['probe']} in its metadata sees only the orders from {p['probe']}",
                    f"HTTP {status}, sees {got} of {want} orders")
            es.send("DELETE", f"/_security/user/{p['probe_user']}")
