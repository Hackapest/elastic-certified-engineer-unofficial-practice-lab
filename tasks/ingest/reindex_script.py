import random

from lib.sampledata import DAYS, ECOMMERCE
from lib.tasklib import Task, get
from tasks.ingest._common import send


class ReindexScript(Task):
    id = "ingest-reindex-script"
    title = "Reindex with a Painless script that reshapes documents"
    covers = ["ingest.reindex.reindex-script", "ingest.reindex.painless", "ingest.reindex.reindex-query"]

    def params(self, rnd, iid):
        return {"dest": f"orders-usd-{iid}", "day": rnd.choice(DAYS), "rate": rnd.choice([1.08, 1.12, 1.17]),
                "qty": rnd.choice([2, 3, 4])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Copy the orders placed on a {p['day']} (field day_of_week) from `{ECOMMERCE}` into a new index
`{p['dest']}`, keeping their ids, and reshape every document during the copy with a Painless
script:

  - rename customer_full_name to `customer`
  - add `total_usd`: taxful_total_price multiplied by the exchange rate, rounded to 2 decimals;
    pass the rate {p['rate']} to the script as a parameter
  - add `basket`: "large" when total_quantity is at least {p['qty']}, otherwise "small"
  - drop the `products` array

All other fields stay as they are.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST _reindex?refresh=true
{{
  "source": {{
    "index": "{ECOMMERCE}",
    "query": {{ "term": {{ "day_of_week": "{p['day']}" }} }}
  }},
  "dest": {{ "index": "{p['dest']}" }},
  "script": {{
    "lang": "painless",
    "source": \"\"\"
      ctx._source.customer = ctx._source.remove('customer_full_name');
      ctx._source.total_usd = Math.round(ctx._source.taxful_total_price * params.rate * 100) / 100.0;
      ctx._source.basket = ctx._source.total_quantity >= params.qty ? 'large' : 'small';
      ctx._source.remove('products');
    \"\"\",
    "params": {{ "rate": {p['rate']}, "qty": {p['qty']} }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = send(es, "HEAD", f"/{p['dest']}")
        if not c.check(status == 200, f"index {p['dest']} exists"):
            return
        send(es, "POST", f"/{p['dest']}/_refresh")
        status, want = send(es, "POST", f"/{ECOMMERCE}/_count", {"query": {"term": {"day_of_week": p["day"]}}})
        status, got = send(es, "POST", f"/{p['dest']}/_count")
        c.equal(get(got, "count"), get(want, "count"), f"all {p['day']} orders were copied (and no others)")
        status, sample = send(es, "POST", f"/{ECOMMERCE}/_search", {"size": 40, "query": {"function_score": {
            "query": {"term": {"day_of_week": p["day"]}}, "random_score": {"seed": random.randrange(10**6),
                                                                           "field": "_seq_no"}}}})
        sample = get(sample, "hits.hits", [])
        status, copies = send(es, "POST", f"/{p['dest']}/_mget", {"ids": [h["_id"] for h in sample]})
        copies = {d["_id"]: d.get("_source") for d in get(copies, "docs", []) if d.get("found")}
        problems = {}
        for h in sample:
            src, copy = h["_source"], copies.get(h["_id"])
            if copy is None:
                problems.setdefault("ids", f"order {h['_id']} is missing (ids must be kept)")
                continue
            if copy.get("customer") != src["customer_full_name"] or "customer_full_name" in copy:
                problems.setdefault("customer", f"order {h['_id']}: customer={copy.get('customer')!r}, "
                                    f"customer_full_name still there: {'customer_full_name' in copy}")
            want_usd = round(src["taxful_total_price"] * p["rate"], 2)
            if not isinstance(copy.get("total_usd"), (int, float)) or abs(copy["total_usd"] - want_usd) > 0.0101:
                problems.setdefault("usd", f"order {h['_id']}: expected total_usd {want_usd}, found {copy.get('total_usd')!r}")
            want_basket = "large" if src["total_quantity"] >= p["qty"] else "small"
            if copy.get("basket") != want_basket:
                problems.setdefault("basket", f"order {h['_id']} (total_quantity {src['total_quantity']}): "
                                    f"expected {want_basket}, found {copy.get('basket')!r}")
            if "products" in copy:
                problems.setdefault("products", f"order {h['_id']} still has products")
            rest = {k: v for k, v in src.items() if k not in ("customer_full_name", "products")}
            if any(copy.get(k) != v for k, v in rest.items()):
                problems.setdefault("rest", f"order {h['_id']}: other fields changed")
        for key, message in [("ids", "the copies keep the ids of the orders"),
                             ("customer", "customer_full_name is renamed to customer"),
                             ("usd", "total_usd is computed and rounded"), ("basket", "basket is set"),
                             ("products", "products is dropped"), ("rest", "the other fields are unchanged")]:
            c.check(key not in problems, message, problems.get(key))
