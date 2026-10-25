import json

from lib.sampledata import CONTINENTS, ECOMMERCE, MANUFACTURERS
from lib.tasklib import Task, get
from tasks.security._helpers import as_user, count, err, search, send_json, setup_orders

PASSWORD = "partner-pass-123"
DOCS = 2000


class DocumentLevel(Task):
    id = "security-document-level"
    title = "Document-level security: a role that only sees some documents"
    covers = ["security.rbac.document-level", "security.rbac.roles", "security.rbac.native-users"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"orders-{iid}", "role": f"partner-{iid}", "user": f"partner-user-{iid}",
                "manufacturer": rnd.choice(MANUFACTURERS[:6]), "continent": rnd.choice(CONTINENTS[:3]),
                "variant": rnd.choice(["manufacturer", "continent"]), "min_total": rnd.choice([40, 60, 80])}

    def setup(self, ctx):
        setup_orders(ctx.es, ctx.p["index"], DOCS)

    def query(self, p):
        if p["variant"] == "manufacturer":
            first = {"term": {"manufacturer.keyword": p["manufacturer"]}}
        else:
            first = {"term": {"geoip.continent_name": p["continent"]}}
        return {"bool": {"filter": [first, {"range": {"taxful_total_price": {"gte": p["min_total"]}}}]}}

    def prompt(self, ctx):
        p = ctx.p
        who = (f"that contain at least one product made by {p['manufacturer']} (field manufacturer)"
               if p["variant"] == "manufacturer"
               else f"from customers in {p['continent']} (field geoip.continent_name)")
        return f"""
A partner may look at some orders in `{p['index']}` on cluster A, and nothing else.

  1. Create the role `{p['role']}` that can read `{p['index']}`, but only the orders {who} with a
     taxful_total_price of {p['min_total']} or more. All other documents must be invisible to it: in
     searches, counts, aggregations and when fetched by ID.
  2. Create the user `{p['user']}` with the password `{PASSWORD}` and that role.
"""

    def solution(self, ctx):
        p = ctx.p
        query = json.dumps(self.query(p), indent=2).replace("\n", "\n      ")
        return f"""
PUT _security/role/{p['role']}
{{
  "indices": [
    {{
      "names": ["{p['index']}"],
      "privileges": ["read"],
      "query": {query}
    }}
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
        want = count(es, p["index"], self.query(p))[1]
        status, got = count(user, p["index"])
        if not c.check(status == 200, f"{p['user']} can search {p['index']}", f"HTTP {status}"):
            return
        c.check(got == want, f"{p['user']} sees exactly the allowed orders", f"sees {got} of the {want} allowed orders"
                f" ({DOCS} in the index)")
        aggs = {"t": {"sum": {"field": "taxful_total_price"}}}
        _, mine = search(user, p["index"], size=0, aggs=aggs)
        _, ref = search(es, p["index"], self.query(p), size=0, aggs=aggs)
        c.check(abs((get(mine, "aggregations.t.value") or 0) - (get(ref, "aggregations.t.value") or 0)) < 0.01,
                "aggregations only include the allowed orders")
        not_allowed = {"bool": {"must_not": [self.query(p)]}}
        _, hidden = search(es, p["index"], not_allowed, size=1)
        doc_id = get(hidden, "hits.hits.0._id")
        status, _ = user.send("GET", f"/{p['index']}/_doc/{doc_id}")
        c.check(status == 404, f"{p['user']} can't fetch other orders by ID", f"GET _doc returned HTTP {status}")
        status, _ = send_json(user, "POST", f"/{p['index']}/_doc", {"x": 1})
        c.check(status == 403, f"{p['user']} can't write to {p['index']}", f"the write returned HTTP {status}")
        status, _ = count(user, ECOMMERCE)
        c.check(status == 403, f"{p['user']} can't read other indices", f"searching {ECOMMERCE} returned HTTP {status}")
