import json

from lib.sampledata import ECOMMERCE
from lib.tasklib import Task, get, index_settings, temp_copy

ALIAS_NAMES = ["storefront", "reporting", "sales"]


class NestedConversionExam(Task):
    id = "ingest-nested-conversion-exam"
    title = "Exam-style: convert an object array to nested with a reindex, and keep the old name"
    covers = ["ingest.types.nested", "ingest.reindex.reindex", "ingest.mapping.update-mapping", "data.aliases.add-remove",
              "data.index.shards-replicas"]
    size = "exam"
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"shop-{iid}", "new": f"shop-fixed-{iid}", "extra": f"{rnd.choice(ALIAS_NAMES)}-{iid}", "docs": 800}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        error = temp_copy(es, ECOMMERCE, p["index"])
        if error:
            raise RuntimeError(error)
        es.post("/_reindex?refresh=true", {"source": {"index": ECOMMERCE}, "dest": {"index": p["index"]},
                                           "max_docs": p["docs"]}, timeout=120)
        p["mappings"] = es.get(f"/{p['index']}/_mapping")[p["index"]]["mappings"]

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{p['index']}`, `products` is a plain object array, so a query can't tell which price belongs to
which product. Fix that:

  1. Reindex `{p['index']}` into the new index `{p['new']}` with 1 primary and 0 replica shards. All
     mappings stay exactly the same, except that the objects in `products` must keep their
     relationships (each product queryable on its own).
  2. Delete `{p['index']}`, and add the aliases `{p['index']}` and `{p['extra']}` to `{p['new']}`.
"""

    def solution(self, ctx):
        p = ctx.p
        mappings = json.loads(json.dumps(p["mappings"]))
        mappings["properties"]["products"]["type"] = "nested"
        return f"""
# The mapping is GET {p['index']}/_mapping, with "type": "nested" added to products:
PUT {p['new']}
{json.dumps({"settings": {"number_of_shards": 1, "number_of_replicas": 0}, "mappings": mappings}, indent=2)}

POST _reindex?refresh=true
{{
  "source": {{ "index": "{p['index']}" }},
  "dest": {{ "index": "{p['new']}" }}
}}

DELETE {p['index']}

POST _aliases
{{
  "actions": [
    {{ "add": {{ "index": "{p['new']}", "alias": "{p['index']}" }} }},
    {{ "add": {{ "index": "{p['new']}", "alias": "{p['extra']}" }} }}
  ]
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        s = index_settings(es, p["new"])
        if not c.check(s is not None, f"index {p['new']} exists"):
            return
        c.equal((s.get("index.number_of_shards"), s.get("index.number_of_replicas")), ("1", "0"), "1 primary, 0 replicas")
        got = es.get(f"/{p['new']}/_mapping")[p["new"]]["mappings"]
        c.equal(get(got, "properties.products.type"), "nested", "products is nested")
        want = json.loads(json.dumps(p["mappings"]))
        want["properties"]["products"]["type"] = "nested"
        different = sorted(k for k in set(want["properties"]) | set(got.get("properties", {}))
                           if want["properties"].get(k) != got.get("properties", {}).get(k))
        c.check(not different, "all other mappings are unchanged", f"different: {', '.join(different[:6])}")
        for alias in (p["index"], p["extra"]):
            status, aliases = es.send("GET", f"/_alias/{alias}")
            c.check(status == 200 and list(aliases) == [p["new"]], f"{alias} is an alias of {p['new']}",
                    f"HTTP {status}: {str(aliases)[:200]}")
        es.send("POST", f"/{p['new']}/_refresh")
        c.equal(es.get(f"/{p['new']}/_count")["count"], p["docs"], "all documents are there")
        found = es.post(f"/{p['new']}/_count", {"query": {"nested": {"path": "products", "query": {"range": {
            "products.price": {"gte": 1}}}}}})["count"]
        c.equal(found, p["docs"], "products can be queried with a nested query")
