from datetime import datetime

from lib.sampledata import ECOMMERCE
from lib.tasklib import Task, get

FIELDS = ["order_date", "taxful_total_price", "total_quantity", "customer_full_name"]


class RuntimeMapped(Task):
    id = "ingest-runtime-mapped"
    title = "Add runtime fields to the mapping of an existing index"
    covers = ["ingest.mapping.runtime-mapped", "ingest.mapping.runtime-retrieve", "ingest.reindex.painless"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"orders-rt-{iid}", "big": rnd.choice([3, 4]), "docs": 300}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"mappings": {"dynamic": False, "properties": {
            "order_date": {"type": "date"}, "taxful_total_price": {"type": "double"},
            "total_quantity": {"type": "integer"}, "customer_full_name": {"type": "keyword"}}}})
        es.post("/_reindex?refresh=true", {"max_docs": p["docs"], "source": {"index": ECOMMERCE, "_source": FIELDS},
                                           "dest": {"index": p["index"]}}, timeout=120)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds orders. Without reindexing or changing its documents, add these
fields to its mapping, computed from the existing fields when they're read:

  price_per_item   (double)   taxful_total_price divided by total_quantity
  order_hour       (long)     the hour of order_date (0-23, UTC)
  big_order        (boolean)  true when total_quantity is {p['big']} or more

They must be searchable and aggregatable like normal fields, and returned with the "fields"
option of a search.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}/_mapping
{{
  "runtime": {{
    "price_per_item": {{
      "type": "double",
      "script": "emit(doc['taxful_total_price'].value / doc['total_quantity'].value)"
    }},
    "order_hour": {{
      "type": "long",
      "script": "emit(doc['order_date'].value.getHour())"
    }},
    "big_order": {{
      "type": "boolean",
      "script": "emit(doc['total_quantity'].value >= {p['big']})"
    }}
  }}
}}

GET {p['index']}/_search
{{
  "fields": ["price_per_item", "order_hour", "big_order"],
  "size": 3
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, mapping = es.send("GET", f"/{p['index']}/_mapping")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return
        runtime = get(mapping, f"{p['index']}.mappings.runtime", {})
        for field, type_ in (("price_per_item", "double"), ("order_hour", "long"), ("big_order", "boolean")):
            c.equal(get(runtime, f"{field}.type"), type_, f"{field} is a {type_} runtime field")
        count = es.get(f"/{p['index']}/_count")["count"]
        c.equal(count, p["docs"], "the documents are unchanged (no reindex)")
        status, response = es.send("POST", f"/{p['index']}/_search", (
            '{"size": 400, "_source": true, "fields": ["price_per_item", "order_hour", "big_order"]}').encode(),
            "application/json")
        if not c.check(status == 200, "a search with the runtime fields works", str(response)[:200]):
            return
        problems = {}
        for hit in get(response, "hits.hits", []):
            src, fields = hit["_source"], hit.get("fields", {})
            expected = {
                "price_per_item": src["taxful_total_price"] / src["total_quantity"],
                "order_hour": datetime.fromisoformat(src["order_date"].replace("Z", "+00:00")).hour,
                "big_order": src["total_quantity"] >= p["big"],
            }
            for field, want in expected.items():
                got = (fields.get(field) or [None])[0]
                ok = abs(got - want) < 1e-6 if isinstance(want, float) and isinstance(got, (int, float)) else got == want
                if not ok:
                    problems.setdefault(field, f"order {hit['_id']}: expected {want!r}, got {got!r}")
        for field in ("price_per_item", "order_hour", "big_order"):
            c.check(field not in problems, f"{field} has the right values", problems.get(field))
