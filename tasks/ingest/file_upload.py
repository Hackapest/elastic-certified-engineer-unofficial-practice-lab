import csv
import io
import json
import random

from lib import config
from lib.tasklib import Task, field_mapping

UPLOADS = config.STATE_DIR / "uploads"
PRODUCTS = ["Desk lamp", "Office chair", "Standing desk", "Monitor arm", "Keyboard", "Webcam", "Headset", "Notebook"]


def rows(seed, count):
    rnd = random.Random(seed)
    return [{"sku": f"SKU-{rnd.randint(10000, 99999)}", "product": rnd.choice(PRODUCTS),
             "price": f"{rnd.uniform(5, 400):.2f}", "in_stock": rnd.choice(["true", "false"]),
             "added": f"2026-{rnd.randint(1, 9):02d}-{rnd.randint(1, 28):02d}"} for _ in range(count)]


class FileUpload(Task):
    id = "ingest-file-upload"
    title = "Upload a CSV file into a new index with Kibana's file upload"
    covers = ["ingest.methods.file-upload", "ingest.mapping.explicit", "ingest.types.keyword", "ingest.types.date"]
    answer = "state"
    requires = ("kibana",)

    def params(self, rnd, iid):
        return {"index": f"products-upload-{iid}", "file": f"products-{iid}.csv", "seed": rnd.randrange(2**31),
                "count": rnd.randint(40, 120)}

    def setup(self, ctx):
        p = ctx.p
        UPLOADS.mkdir(parents=True, exist_ok=True)
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=["sku", "product", "price", "in_stock", "added"])
        writer.writeheader()
        writer.writerows(rows(p["seed"], p["count"]))
        (UPLOADS / p["file"]).write_text(out.getvalue())

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The file {UPLOADS / p['file']} (in WSL; from Windows open
\\\\wsl$ in the Explorer to find it) holds {p['count']} products as CSV. Load it into cluster A with Kibana's
file upload (Kibana A menu: search for "Upload a file"), into the new index `{p['index']}`.

Before importing, check the mapping Kibana suggests and make sure that:
  sku is a keyword, product is text, price is a number with decimals (double or float),
  in_stock is a boolean, and added is a date.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# In Kibana A: menu -> "Upload a file" -> select {p['file']} -> check the analysis ->
# Import -> Advanced: index name {p['index']}, check/adjust the mapping, e.g.
{{
  "properties": {{
    "sku": {{ "type": "keyword" }},
    "product": {{ "type": "text" }},
    "price": {{ "type": "double" }},
    "in_stock": {{ "type": "boolean" }},
    "added": {{ "type": "date", "format": "yyyy-MM-dd" }}
  }}
}}
# -> Import. Then: GET {p['index']}/_count
"""

    def apply_solution(self, ctx):
        # Selftest can't click through Kibana; create what the upload creates
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"mappings": {"properties": {
            "sku": {"type": "keyword"}, "product": {"type": "text"}, "price": {"type": "double"},
            "in_stock": {"type": "boolean"}, "added": {"type": "date", "format": "yyyy-MM-dd"}}}})
        bulk = "".join('{"index":{}}\n' + json.dumps(r) + "\n" for r in rows(p["seed"], p["count"]))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")
        return None

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/{p['index']}/_count")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return
        c.equal(response.get("count"), p["count"], f"it holds all {p['count']} products")
        types = {f: (field_mapping(es, p["index"], f) or {}).get("type") for f in ("sku", "product", "price", "in_stock", "added")}
        c.equal(types["sku"], "keyword", "sku is a keyword")
        c.equal(types["product"], "text", "product is text")
        c.check(types["price"] in ("double", "float", "half_float", "scaled_float"), "price is a decimal number",
                f"it is {types['price']}")
        c.equal(types["in_stock"], "boolean", "in_stock is a boolean")
        c.equal(types["added"], "date", "added is a date")

    def cleanup(self, ctx):
        (UPLOADS / ctx.p["file"]).unlink(missing_ok=True)
