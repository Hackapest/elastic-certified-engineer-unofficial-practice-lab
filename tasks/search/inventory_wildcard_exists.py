import json
import random

from lib.tasklib import Task

LINES = {"SHO": "shoes", "BAG": "bags", "ACC": "accessories", "CLO": "clothing"}
SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
SIZE_RULES = {   # description, wildcard for the size part
    "XS or XL": "X?",
    "a one-letter size (S, M or L)": "?",
    "any size ending in L (L, XL, XXL)": "*L",
}


class InventoryWildcardExists(Task):
    id = "search-inventory-wildcard-exists"
    title = "Match SKU patterns and present or missing fields (wildcard, exists)"
    covers = ["search.term.wildcard", "search.term.exists", "search.compound.bool"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        return {"index": f"inventory-{iid}", "seed": rnd.randrange(10**6), "line": rnd.choice(sorted(LINES)),
                "size_rule": rnd.choice(sorted(SIZE_RULES))}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        rnd = random.Random(p["seed"])
        es.put(f"/{p['index']}", {"mappings": {"properties": {
            "sku": {"type": "keyword"}, "name": {"type": "text"}, "discount_pct": {"type": "integer"},
            "discontinued_on": {"type": "date"}, "stock": {"type": "integer"}}}})
        lines = []
        for i in range(400):
            line, size = rnd.choice(sorted(LINES)), rnd.choice(SIZES)
            doc = {"sku": f"{line}-{rnd.randrange(10000):04d}-{size}", "name": f"{LINES[line]} item {i}",
                   "stock": rnd.randrange(0, 200)}
            if rnd.random() < 0.5:
                doc["discount_pct"] = rnd.choice([5, 10, 15, 20, 30])
            if rnd.random() < 0.3:
                doc["discontinued_on"] = f"2025-{rnd.randrange(1, 13):02d}-{rnd.randrange(1, 29):02d}"
            lines.append(json.dumps({"index": {"_id": str(i)}}) + "\n" + json.dumps(doc) + "\n")
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", "".join(lines).encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds products. Their SKUs (sku, a keyword field) look like
"<LINE>-<4 digits>-<SIZE>", e.g. "SHO-0042-XL". Some products have a discount (field
discount_pct) and some are discontinued (field discontinued_on); products without them simply
don't have the field.

Find the products that:
  - are in the line "{p['line']}" and come in {p['size_rule']}, judging by the SKU;
  - have a discount (discount_pct is present);
  - are NOT discontinued (no discontinued_on field).

Return all of them in one response.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {p['index']}/_search
{{
  "size": 1000,
  "query": {{
    "bool": {{
      "filter": [
        {{ "wildcard": {{ "sku": "{p['line']}-*-{SIZE_RULES[p['size_rule']]}" }} }},
        {{ "exists": {{ "field": "discount_pct" }} }}
      ],
      "must_not": [
        {{ "exists": {{ "field": "discontinued_on" }} }}
      ]
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Keeps the discontinued products
        return self.solution(ctx).replace('{ "exists": { "field": "discontinued_on" } }', '{ "ids": { "values": ["none"] } }')
