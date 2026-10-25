from lib.sampledata import ECOMMERCE
from lib.tasklib import Task, get
from tasks.security._helpers import as_user, count, same_sources, setup_orders

PASSWORD = "support-pass-123"
DOCS = 300


class FieldLevel(Task):
    id = "security-field-level"
    title = "Field-level security: show only some fields of an index to a role"
    covers = ["security.rbac.field-level", "security.rbac.roles"]
    answer = "state"

    def params(self, rnd, iid):
        variant = rnd.choice(["grant", "except"])
        if variant == "grant":
            grant = ["order_id", "order_date", "taxful_total_price", "category",
                     rnd.choice(["currency", "day_of_week", "manufacturer"]),
                     "products.product_name", rnd.choice(["products.quantity", "products.price"])]
            exclude = []
        else:
            grant = ["*"]
            exclude = ["customer_*", "email", "user"] + rnd.sample(["geoip.*", "products.base_price",
                                                                     "products.min_price", "taxless_total_price"], 2)
        return {"index": f"orders-{iid}", "role": f"support-{iid}", "user": f"support-agent-{iid}",
                "variant": variant, "grant": grant, "exclude": exclude}

    def setup(self, ctx):
        setup_orders(ctx.es, ctx.p["index"], DOCS)

    def prompt(self, ctx):
        p = ctx.p
        if p["variant"] == "grant":
            fields = "\n".join(f"       - {f}" for f in p["grant"])
            rule = f"""It may only see these fields of the documents (everything else is hidden, also
     from queries):
{fields}"""
        else:
            fields = "\n".join(f"       - {f}" for f in p["exclude"])
            rule = f"""It may see every field of the documents except these (they must be hidden,
     also from queries; a `*` stands for any characters):
{fields}"""
        return f"""
The support team must not see customer personal data in the index `{p['index']}` on cluster A.

  1. Create the role `{p['role']}` that can read `{p['index']}`. {rule}
  2. Create the user `{p['user']}` with the password `{PASSWORD}` and that role.
"""

    def solution(self, ctx):
        p = ctx.p
        fs = '"grant": [' + ", ".join(f'"{f}"' for f in p["grant"]) + "]"
        if p["exclude"]:
            fs += ', "except": [' + ", ".join(f'"{f}"' for f in p["exclude"]) + "]"
        return f"""
PUT _security/role/{p['role']}
{{
  "indices": [
    {{
      "names": ["{p['index']}"],
      "privileges": ["read"],
      "field_security": {{ {fs} }}
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
        status, got = count(user, p["index"])
        if not c.check(status == 200 and got == DOCS, f"{p['user']} can read all documents of {p['index']}",
                       f"HTTP {status}, {got} documents"):
            return
        same_sources(c, user, es, p["index"], p["grant"], p["exclude"],
                     f"{p['user']} sees exactly the allowed fields")
        query = {"term": {"customer_gender": "MALE"}}
        status, got = count(user, p["index"], query)
        c.check(status == 200 and got == 0, f"{p['user']} can't query hidden fields",
                f"a query on customer_gender matched {got} documents")
        status, _ = count(user, ECOMMERCE)
        c.check(status == 403, f"{p['user']} can't read other indices", f"searching {ECOMMERCE} returned HTTP {status}")
