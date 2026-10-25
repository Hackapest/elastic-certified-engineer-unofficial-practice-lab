from lib.tasklib import Task, field_mapping, index_settings


class IndexCreateSorted(Task):
    id = "data-index-create-sorted"
    title = "Create an index with sorting, compression and shard settings"
    covers = ["data.index.index-sorting", "data.index.codec", "data.index.shards-replicas",
              "ingest.mapping.explicit", "ingest.types.date", "ingest.types.keyword"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"events-{iid}", "shards": rnd.choice([2, 3, 4]), "replicas": rnd.choice([0, 1]),
                "second": rnd.choice(["severity", "host"]), "second_order": rnd.choice(["asc", "desc"])}

    def prompt(self, ctx):
        p = ctx.p
        direction = "A to Z" if p["second_order"] == "asc" else "Z to A"
        return f"""
Create the index `{p['index']}` with {p['shards']} primary shards and {p['replicas']} replica(s), stored with the
best (slower, smaller) compression. It has these fields:

  timestamp   a date
  {p['second']:<10}  an exact value (keyword)
  message     full text

On disk, its documents must be sorted by timestamp, newest first, then by {p['second']}, {direction}.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "settings": {{
    "number_of_shards": {p['shards']},
    "number_of_replicas": {p['replicas']},
    "codec": "best_compression",
    "sort.field": ["timestamp", "{p['second']}"],
    "sort.order": ["desc", "{p['second_order']}"]
  }},
  "mappings": {{
    "properties": {{
      "timestamp": {{ "type": "date" }},
      "{p['second']}": {{ "type": "keyword" }},
      "message": {{ "type": "text" }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        s = index_settings(es, p["index"])
        if not c.check(s is not None, f"index {p['index']} exists"):
            return
        c.equal(s.get("index.number_of_shards"), str(p["shards"]), "number of primary shards")
        c.equal(s.get("index.number_of_replicas"), str(p["replicas"]), "number of replicas")
        c.equal(s.get("index.codec"), "best_compression", "best compression codec")
        fields = [s.get(f"index.sort.field.{i}") for i in range(2)] if "index.sort.field.0" in s \
            else s.get("index.sort.field")
        orders = [s.get(f"index.sort.order.{i}") for i in range(2)] if "index.sort.order.0" in s \
            else s.get("index.sort.order")
        c.equal(fields, ["timestamp", p["second"]], "sorted by timestamp, then " + p["second"])
        c.equal(orders, ["desc", p["second_order"]], "sort orders")
        for field, type_ in (("timestamp", "date"), (p["second"], "keyword"), ("message", "text")):
            c.equal((field_mapping(es, p["index"], field) or {}).get("type"), type_, f"{field} is a {type_} field")
