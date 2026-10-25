import json
import random

from lib.tasklib import Task, get
from tasks.ingest._common import bulk, send


def stock(seed):
    rnd = random.Random(seed)
    return {str(n): {"sku": f"SKU-{100 + n}", "qty": rnd.randint(1, 50), "price": rnd.randint(5, 90),
                     "status": "active"} for n in range(1, 7)}


class BulkActions(Task):
    id = "ingest-bulk-actions"
    title = "One bulk request with index, create, update and delete actions"
    covers = ["ingest.methods.bulk", "ingest.methods.document-apis", "ingest.reindex.painless"]

    def params(self, rnd, iid):
        ids = rnd.sample(["2", "3", "4", "5", "6"], 4)
        return {"index": f"inventory-{iid}", "archive": f"inventory-archive-{iid}", "seed": rnd.randrange(10**6),
                "upd": ids[0], "inc": ids[1], "dele": ids[2], "new_qty": rnd.randint(60, 99),
                "by": rnd.randint(2, 9), "new_id": str(rnd.randint(20, 40)), "new_sku": f"SKU-{rnd.randint(500, 599)}"}

    def setup(self, ctx):
        p = ctx.p
        docs = stock(p["seed"])
        bulk(ctx.es, p["index"], list(docs.values()), ids=list(docs))

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds documents with ids 1 to 6 ({{"sku", "qty", "price", "status"}}).
With ONE bulk request:

  1. add a document with id {p['new_id']}: {{ "sku": "{p['new_sku']}", "qty": 10, "price": 15, "status": "active" }}
     in a way that fails instead of overwriting if that id already exists
  2. try to add a document with id 1, {{ "sku": "SKU-DUP", "qty": 0, "price": 0, "status": "new" }}, the same
     way: this action must fail and leave document 1 untouched
  3. set qty of document {p['upd']} to {p['new_qty']} (partial update; the other fields stay)
  4. increase qty of document {p['inc']} by {p['by']} with a script that takes the amount as a parameter
  5. delete document {p['dele']}
  6. add a copy of document {p['dele']} (same id and fields) to the index `{p['archive']}`, with
     status set to "archived"
"""

    def solution(self, ctx):
        p = ctx.p
        old = dict(stock(p["seed"])[p["dele"]], status="archived")
        return f"""
POST _bulk?refresh=true
{{ "create": {{ "_index": "{p['index']}", "_id": "{p['new_id']}" }} }}
{{ "sku": "{p['new_sku']}", "qty": 10, "price": 15, "status": "active" }}
{{ "create": {{ "_index": "{p['index']}", "_id": "1" }} }}
{{ "sku": "SKU-DUP", "qty": 0, "price": 0, "status": "new" }}
{{ "update": {{ "_index": "{p['index']}", "_id": "{p['upd']}" }} }}
{{ "doc": {{ "qty": {p['new_qty']} }} }}
{{ "update": {{ "_index": "{p['index']}", "_id": "{p['inc']}" }} }}
{{ "script": {{ "source": "ctx._source.qty += params.by", "params": {{ "by": {p['by']} }} }} }}
{{ "delete": {{ "_index": "{p['index']}", "_id": "{p['dele']}" }} }}
{{ "index": {{ "_index": "{p['archive']}", "_id": "{p['dele']}" }} }}
{json.dumps(old)}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        docs = stock(p["seed"])
        status, response = send(es, "POST", f"/{p['index']}/_mget", {"ids": [str(n) for n in range(1, 7)] + [p["new_id"]]})
        got = {d["_id"]: d.get("_source") if d.get("found") else None for d in get(response, "docs", [])}
        c.equal(got.get(p["new_id"]), {"sku": p["new_sku"], "qty": 10, "price": 15, "status": "active"},
                f"document {p['new_id']} was added")
        c.equal(got.get("1"), docs["1"], "document 1 is unchanged")
        c.equal(got.get(p["upd"]), dict(docs[p["upd"]], qty=p["new_qty"]), f"document {p['upd']} has the new qty")
        c.equal(got.get(p["inc"]), dict(docs[p["inc"]], qty=docs[p["inc"]]["qty"] + p["by"]),
                f"document {p['inc']}'s qty was increased by {p['by']}")
        c.equal(got.get(p["dele"], "?"), None, f"document {p['dele']} was deleted")
        status, response = send(es, "GET", f"/{p['archive']}/_doc/{p['dele']}")
        c.equal(get(response, "_source") if status == 200 else None, dict(docs[p["dele"]], status="archived"),
                f"{p['archive']} has the archived copy of document {p['dele']}")
        untouched = [n for n in docs if n not in (p["upd"], p["inc"], p["dele"], "1")]
        c.check(all(got.get(n) == docs[n] for n in untouched), "the other documents are unchanged")
