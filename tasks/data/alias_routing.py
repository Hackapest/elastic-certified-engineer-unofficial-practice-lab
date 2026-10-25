import json

from lib.tasklib import Task, get

CUSTOMERS = ["acme", "globex", "initech", "umbrella", "hooli", "stark"]


class AliasRouting(Task):
    id = "data-alias-routing"
    title = "Per-customer aliases with routing and filters"
    covers = ["data.aliases.routing", "data.aliases.filtered", "data.aliases.add-remove"]
    answer = "state"

    def params(self, rnd, iid):
        customer, *report = rnd.sample(CUSTOMERS, 3)
        return {"index": f"tickets-{iid}", "alias": f"tickets-{customer}-{iid}", "customer": customer,
                "report": sorted(report), "report_alias": f"tickets-report-{iid}", "docs": rnd.randint(60, 120)}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"settings": {"number_of_shards": 4, "number_of_replicas": 0},
                                 "mappings": {"properties": {"customer": {"type": "keyword"},
                                                             "subject": {"type": "text"}}}})
        bulk = "".join(f'{{"index":{{"routing":"{CUSTOMERS[i % len(CUSTOMERS)]}"}}}}\n'
                       f'{{"customer":"{CUSTOMERS[i % len(CUSTOMERS)]}","subject":"ticket {i}"}}\n'
                       for i in range(p["docs"]))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds support tickets of all customers. Each document has a `customer`
field, and was indexed with the customer ID as its routing value.

  1. Create the alias `{p['alias']}` for the customer "{p['customer']}": searches through it must
     only return that customer's tickets and only query the shard that holds them, and documents
     indexed through it must be routed with "{p['customer']}".
  2. Create the alias `{p['report_alias']}` for a report over the customers {' and '.join(p['report'])}:
     searches through it must only hit the shards that hold their tickets (you don't need a filter
     for this alias). It is not used for indexing.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST _aliases
{{
  "actions": [
    {{
      "add": {{
        "index": "{p['index']}",
        "alias": "{p['alias']}",
        "filter": {{ "term": {{ "customer": "{p['customer']}" }} }},
        "routing": "{p['customer']}"
      }}
    }},
    {{
      "add": {{
        "index": "{p['index']}",
        "alias": "{p['report_alias']}",
        "search_routing": "{','.join(p['report'])}"
      }}
    }}
  ]
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        per_customer = lambda name: sum(1 for i in range(p["docs"]) if CUSTOMERS[i % len(CUSTOMERS)] == name)
        aliases = get(es.send("GET", f"/{p['index']}/_alias")[1] or {}, f"{p['index']}.aliases", {})
        a = aliases.get(p["alias"])
        if c.check(a is not None, f"alias {p['alias']} exists on {p['index']}"):
            c.equal((a.get("index_routing"), a.get("search_routing")), (p["customer"], p["customer"]),
                    "it routes indexing and searches by the customer")
            count = (es.send("GET", f"/{p['alias']}/_count")[1] or {}).get("count")
            c.equal(count, per_customer(p["customer"]), f"it returns exactly the tickets of {p['customer']}")
            status, doc = es.send("POST", f"/{p['alias']}/_doc", json.dumps(
                {"customer": p["customer"], "subject": "probe"}).encode(), "application/json")
            if c.check(status == 201, "documents can be indexed through it", f"HTTP {status}: {str(doc)[:200]}"):
                got = es.send("GET", f"/{p['index']}/_doc/{doc['_id']}?routing={p['customer']}")[1] or {}
                c.equal(got.get("_routing"), p["customer"], "indexed documents get the customer as routing")
                es.send("DELETE", f"/{p['index']}/_doc/{doc['_id']}?routing={p['customer']}&refresh=true")
        r = aliases.get(p["report_alias"])
        if c.check(r is not None, f"alias {p['report_alias']} exists on {p['index']}"):
            routing = sorted((r.get("search_routing") or "").split(","))
            c.equal(routing, p["report"], f"its searches are routed to {' and '.join(p['report'])}")
            body = json.dumps({"size": 0, "aggs": {"c": {"terms": {"field": "customer", "size": 10}}}}).encode()
            res = es.send("POST", f"/{p['report_alias']}/_search", body, "application/json")[1] or {}
            shards = get(res, "_shards.total")
            c.check(shards is not None and shards <= 2, "searches through it hit at most 2 shards",
                    f"a search hit {shards} shards")
