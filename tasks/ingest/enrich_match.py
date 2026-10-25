import random

from lib.tasklib import Task, get
from tasks.ingest._common import MISSING, bulk, field, pipeline_exists, send, simulate

FIRST = ["ana", "ben", "chloe", "dev", "eva", "farid", "gus", "hana", "ivan", "jo", "kim", "lena", "max", "nia"]
TIERS = ["gold", "silver", "bronze"]
COUNTRIES = ["DE", "FR", "US", "JP", "BR", "IN"]


def customers(seed):
    rnd = random.Random(seed)
    return [{"email": f"{n}@example.com", "name": n.title() + " " + rnd.choice(["Ray", "Moss", "Hart", "Lund"]),
             "tier": rnd.choice(TIERS), "country": rnd.choice(COUNTRIES), "phone": f"+1-555-{rnd.randint(1000, 9999)}"}
            for n in FIRST]


class EnrichMatch(Task):
    id = "ingest-enrich-match"
    title = "Enrich orders with customer data (match enrich policy, enrich processor, reindex through it)"
    covers = ["ingest.pipelines.enrich-policy", "ingest.pipelines.processor.enrich",
              "ingest.reindex.reindex-pipeline", "ingest.pipelines.use-on-request"]

    def params(self, rnd, iid):
        return {"customers": f"customers-{iid}", "orders_raw": f"orders-raw-{iid}", "orders": f"orders-{iid}",
                "policy": f"customer-lookup-{iid}", "pipeline": f"orders-enrich-{iid}",
                "seed": rnd.randrange(10**6), "target": rnd.choice(["customer", "buyer"]),
                "fields": rnd.choice([["name", "tier"], ["tier", "country"], ["name", "country", "tier"]])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        cs = customers(p["seed"])
        es.put(f"/{p['customers']}", {"mappings": {"properties": {
            "email": {"type": "keyword"}, "name": {"type": "text"}, "tier": {"type": "keyword"},
            "country": {"type": "keyword"}, "phone": {"type": "keyword"}}}})
        bulk(es, p["customers"], cs)
        rnd = random.Random(p["seed"] + 1)
        emails = [c["email"] for c in cs] + ["unknown@example.org"]
        orders = [{"order_id": f"o-{n}", "customer_email": rnd.choice(emails), "amount": rnd.randint(5, 400)}
                  for n in range(40)]
        bulk(es, p["orders_raw"], orders)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['customers']}` holds customers (email, name, tier, country, phone) and
`{p['orders_raw']}` holds orders that refer to a customer by `customer_email`.

  1. Create an enrich policy `{p['policy']}` that looks customers up by email and provides the
     fields {", ".join(p['fields'])} (and only those, besides the email). Make it usable.
  2. Create an ingest pipeline `{p['pipeline']}` that adds the matching customer's data under
     `{p['target']}` (e.g. {p['target']}.{p['fields'][0]}). Orders whose email matches no customer are
     indexed unchanged.
  3. Copy all orders from `{p['orders_raw']}` into a new index `{p['orders']}` through that pipeline.
"""

    def solution(self, ctx):
        p = ctx.p
        fields = ", ".join(f'"{f}"' for f in p["fields"])
        return f"""
PUT _enrich/policy/{p['policy']}
{{
  "match": {{
    "indices": "{p['customers']}",
    "match_field": "email",
    "enrich_fields": [{fields}]
  }}
}}

POST _enrich/policy/{p['policy']}/_execute

PUT _ingest/pipeline/{p['pipeline']}
{{
  "processors": [
    {{
      "enrich": {{
        "policy_name": "{p['policy']}",
        "field": "customer_email",
        "target_field": "{p['target']}"
      }}
    }}
  ]
}}

POST _reindex?refresh=true
{{
  "source": {{ "index": "{p['orders_raw']}" }},
  "dest": {{ "index": "{p['orders']}", "pipeline": "{p['pipeline']}" }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = send(es, "GET", f"/_enrich/policy/{p['policy']}")
        policies = get(response, "policies", []) if status == 200 else []
        if c.check(policies, f"enrich policy {p['policy']} exists"):
            conf = get(policies[0], "config.match")
            if c.check(conf is not None, "it is a match policy"):
                c.equal(conf.get("match_field"), "email", "it matches on email")
                c.equal(sorted(conf.get("enrich_fields", [])), sorted(p["fields"]), "it provides the requested fields")
        status, response = send(es, "GET", f"/_resolve/index/.enrich-{p['policy']}-*?expand_wildcards=all")
        c.check(status == 200 and get(response, "indices"), "the policy has been executed",
                "no enrich index found: execute the policy")
        if not pipeline_exists(c, es, p["pipeline"]):
            return
        cs = {x["email"]: x for x in customers(p["seed"])}
        rnd = random.Random()
        emails = rnd.sample(sorted(cs), 6) + ["nobody@example.net"]
        got, error = simulate(es, [{"customer_email": e, "amount": 1} for e in emails], pipeline=p["pipeline"])
        if not c.check(error is None, "the pipeline can be simulated", error):
            return
        bad = None
        for e, r in zip(emails, got):
            if r["error"]:
                bad = bad or f"for {e}: {r['error']}"
                continue
            target = field(r["source"], p["target"])
            if e not in cs:
                if target is not MISSING:
                    bad = bad or f"for unknown {e}: expected no {p['target']} field, found {target!r}"
                continue
            want = {f: cs[e][f] for f in p["fields"]}
            have = {f: field(target, f) if isinstance(target, dict) else MISSING for f in p["fields"]}
            if have != want:
                bad = bad or f"for {e}: expected {want}, found {target!r}"
        c.check(bad is None, f"the pipeline adds the customer data under {p['target']}", bad)
        status, response = send(es, "GET", f"/{p['orders']}/_count")
        status_raw, raw = send(es, "GET", f"/{p['orders_raw']}/_count")
        if c.check(status == 200, f"index {p['orders']} exists"):
            c.equal(response.get("count"), raw.get("count"), f"{p['orders']} has all the orders (refresh it if needed)")
            status, response = send(es, "GET", f"/{p['orders']}/_count",
                                    {"query": {"exists": {"field": f"{p['target']}.{p['fields'][0]}"}}})
            status, known = send(es, "GET", f"/{p['orders_raw']}/_count", {"query": {"bool": {"must_not": {
                "term": {"customer_email.keyword": "unknown@example.org"}}}}})
            c.equal(get(response, "count"), get(known, "count"),
                    "every order with a known customer was enriched on the way")
