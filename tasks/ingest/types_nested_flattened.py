import json
import random

from lib.tasklib import Task, field_mapping, get
from tasks.ingest._common import send

AUTHORS = ["kim", "lee", "ana", "raj", "tom", "eve"]
ATTRS = {"color": ["red", "blue", "green"], "size": ["S", "M", "L"], "material": ["wool", "cotton"],
         "voltage": ["110V", "230V"], "fit": ["slim", "regular"]}


def products(seed):
    rnd = random.Random(seed)
    docs = []
    for n in range(8):
        reviews = [{"author": a, "stars": rnd.randint(1, 5), "text": rnd.choice(["great", "meh", "broke fast",
                                                                                   "love it"])}
                   for a in rnd.sample(AUTHORS, rnd.randint(1, 3))]
        attrs = {k: rnd.choice(v) for k, v in rnd.sample(sorted(ATTRS.items()), rnd.randint(1, 3))}
        docs.append({"id": f"p{n}", "name": f"Product {n}", "seller": {"name": rnd.choice(["Acme", "Globex"]),
                     "rating": round(rnd.uniform(1, 5), 1)}, "reviews": reviews, "attributes": attrs})
    return docs


class TypesNestedFlattened(Task):
    id = "ingest-types-nested-flattened"
    title = "Choose between object, nested and flattened for structured data, then bulk index it"
    covers = ["ingest.types.nested", "ingest.types.flattened", "ingest.types.object", "ingest.methods.bulk",
              "ingest.mapping.explicit"]

    def params(self, rnd, iid):
        return {"index": f"catalog-{iid}", "seed": rnd.randrange(10**6)}

    def prompt(self, ctx):
        p = ctx.p
        docs = products(p["seed"])
        return f"""
Products look like this (the full set is listed below):

  {json.dumps(docs[0])}

Create the index `{p['index']}` with a mapping that meets these requirements:

  - a query for reviews by a given author with a given number of stars must only match products
    that have ONE review satisfying both conditions (reviews.author and reviews.stars, which are
    an exact value and an integer; reviews.text is full text)
  - `attributes` holds arbitrary keys chosen by the sellers: new keys must never add fields to
    the mapping, yet each attribute must be searchable as an exact value (attributes.color: red)
  - seller is a plain object with name (exact value) and rating (a float)
  - id is an exact value, name is full text

Then index the 8 products with one bulk request, using each product's `id` as the document _id:

{chr(10).join("  " + json.dumps(d) for d in docs)}
"""

    def solution(self, ctx):
        p = ctx.p
        lines = "\n".join(f'{{ "index": {{ "_id": "{d["id"]}" }} }}\n{json.dumps(d)}' for d in products(p["seed"]))
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "properties": {{
      "id": {{ "type": "keyword" }},
      "name": {{ "type": "text" }},
      "seller": {{
        "properties": {{
          "name": {{ "type": "keyword" }},
          "rating": {{ "type": "float" }}
        }}
      }},
      "reviews": {{
        "type": "nested",
        "properties": {{
          "author": {{ "type": "keyword" }},
          "stars": {{ "type": "integer" }},
          "text": {{ "type": "text" }}
        }}
      }},
      "attributes": {{ "type": "flattened" }}
    }}
  }}
}}

POST {p['index']}/_bulk?refresh=true
{lines}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = send(es, "HEAD", f"/{p['index']}")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return
        f = lambda name: field_mapping(es, p["index"], name) or {}
        c.equal(f("reviews").get("type"), "nested", "reviews is nested")
        c.equal((f("reviews.author").get("type"), f("reviews.stars").get("type"), f("reviews.text").get("type")),
                ("keyword", "integer", "text"), "the review fields have the requested types")
        c.equal(f("attributes").get("type"), "flattened", "attributes is flattened")
        s = f("seller")
        c.check(s.get("type", "object") == "object" and f("seller.name").get("type") == "keyword"
                and f("seller.rating").get("type") == "float", "seller is an object with keyword name and float rating",
                f"found {s}")
        c.equal((f("id").get("type"), f("name").get("type")), ("keyword", "text"), "id is keyword, name is text")
        docs = products(p["seed"])
        send(es, "POST", f"/{p['index']}/_refresh")
        status, response = send(es, "GET", f"/{p['index']}/_search", {"size": 20, "_source": False})
        ids = sorted(h["_id"] for h in get(response, "hits.hits", []))
        c.equal(ids, sorted(d["id"] for d in docs), "the 8 products are indexed with their id as _id")
        # nested behaviour: author+stars from different reviews must not match
        r = docs[0]["reviews"][0]
        expected = sorted(d["id"] for d in docs if any(x["author"] == r["author"] and x["stars"] == r["stars"]
                                                        for x in d["reviews"]))
        status, response = send(es, "GET", f"/{p['index']}/_search", {"size": 20, "_source": False, "query": {
            "nested": {"path": "reviews", "query": {"bool": {"filter": [
                {"term": {"reviews.author": r["author"]}}, {"term": {"reviews.stars": r["stars"]}}]}}}}})
        c.equal(sorted(h["_id"] for h in get(response, "hits.hits", [])), expected,
                "a nested query on author and stars finds the right products")
        k, v = next(iter(docs[1]["attributes"].items()))
        status, response = send(es, "GET", f"/{p['index']}/_count", {"query": {"term": {f"attributes.{k}": v}}})
        c.equal(get(response, "count"), sum(1 for d in docs if d["attributes"].get(k) == v),
                f"attributes.{k} is searchable as an exact value")
