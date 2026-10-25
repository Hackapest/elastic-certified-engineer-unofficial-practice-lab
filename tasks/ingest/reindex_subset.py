import json

from lib.sampledata import ALL_CATEGORIES, DAYS, ECOMMERCE
from lib.tasklib import Task, field_mapping, get
from tasks.ingest._common import send

FIELDS = ["order_id", "order_date", "customer_full_name", "taxful_total_price", "category"]


class ReindexSubset(Task):
    id = "ingest-reindex-subset"
    title = "Reindex a filtered subset with source filtering into a predefined mapping, and a capped sample"
    covers = ["ingest.reindex.reindex", "ingest.reindex.reindex-query", "ingest.mapping.explicit",
              "ingest.types.numeric"]

    def params(self, rnd, iid):
        return {"dest": f"big-orders-{iid}", "sample": f"orders-sample-{iid}", "category": rnd.choice(ALL_CATEGORIES),
                "min": rnd.choice([60, 80, 100, 120]), "day": rnd.choice(DAYS), "max": rnd.choice([25, 50, 75])}

    def source_query(self, p):
        return {"bool": {"filter": [{"term": {"category.keyword": p["category"]}},
                                    {"range": {"taxful_total_price": {"gte": p["min"]}}}]}}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
1. Create the index `{p['dest']}` with this mapping:
     order_id keyword, order_date date, customer_full_name text, taxful_total_price scaled_float
     (scaling factor 100), category keyword.

2. Copy into it, from `{ECOMMERCE}`, only the orders that contain the category "{p['category']}"
   (field category) and whose taxful_total_price is at least {p['min']}. Copy only the five fields of
   the mapping above; the documents keep their ids.

3. Copy exactly {p['max']} orders placed on a {p['day']} (field day_of_week), any of them, with all their fields,
   into a new index `{p['sample']}`.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['dest']}
{{
  "mappings": {{
    "properties": {{
      "order_id": {{ "type": "keyword" }},
      "order_date": {{ "type": "date" }},
      "customer_full_name": {{ "type": "text" }},
      "taxful_total_price": {{ "type": "scaled_float", "scaling_factor": 100 }},
      "category": {{ "type": "keyword" }}
    }}
  }}
}}

POST _reindex?refresh=true
{{
  "source": {{
    "index": "{ECOMMERCE}",
    "query": {{
      "bool": {{
        "filter": [
          {{ "term": {{ "category.keyword": "{p['category']}" }} }},
          {{ "range": {{ "taxful_total_price": {{ "gte": {p['min']} }} }} }}
        ]
      }}
    }},
    "_source": {json.dumps(FIELDS)}
  }},
  "dest": {{ "index": "{p['dest']}" }}
}}

POST _reindex?refresh=true
{{
  "max_docs": {p['max']},
  "source": {{
    "index": "{ECOMMERCE}",
    "query": {{ "term": {{ "day_of_week": "{p['day']}" }} }}
  }},
  "dest": {{ "index": "{p['sample']}" }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = send(es, "HEAD", f"/{p['dest']}")
        if c.check(status == 200, f"index {p['dest']} exists"):
            types = {f: (field_mapping(es, p["dest"], f) or {}).get("type") for f in FIELDS}
            c.equal(types, {"order_id": "keyword", "order_date": "date", "customer_full_name": "text",
                            "taxful_total_price": "scaled_float", "category": "keyword"},
                    "the mapping has the requested types")
            c.equal(set(get(es.get(f"/{p['dest']}/_mapping"), f"{p['dest']}.mappings.properties", {})), set(FIELDS),
                    "no other fields were added to the mapping")
            send(es, "POST", f"/{p['dest']}/_refresh")
            status, want = send(es, "POST", f"/{ECOMMERCE}/_search", {"size": 5000, "_source": False,
                                                                     "query": self.source_query(p)})
            want_ids = sorted(h["_id"] for h in get(want, "hits.hits", []))
            status, got = send(es, "POST", f"/{p['dest']}/_search", {"size": 5000, "_source": False})
            got_ids = sorted(h["_id"] for h in get(got, "hits.hits", []))
            c.check(got_ids == want_ids, "exactly the matching orders were copied, with their ids",
                    f"expected {len(want_ids)} documents, found {len(got_ids)}")
            status, got = send(es, "POST", f"/{p['dest']}/_search", {"size": 1})
            src = get(got, "hits.hits.0._source", {})
            c.check(src and set(src) <= set(FIELDS), "only the five fields were copied", f"a document has {sorted(src)}")
        status, _ = send(es, "HEAD", f"/{p['sample']}")
        if c.check(status == 200, f"index {p['sample']} exists"):
            send(es, "POST", f"/{p['sample']}/_refresh")
            status, got = send(es, "POST", f"/{p['sample']}/_search", {"size": 200})
            hits = get(got, "hits.hits", [])
            c.equal(len(hits), p["max"], f"{p['sample']} has exactly {p['max']} orders")
            c.check(hits and all(get(h, "_source.day_of_week") == p["day"] and "products" in h["_source"] for h in hits),
                    f"they are all {p['day']} orders with all their fields")
