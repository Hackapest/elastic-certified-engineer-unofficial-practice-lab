import json

from lib.tasklib import Task, field_mapping, get
from tasks.ingest._common import send


class TypesSpecial(Task):
    id = "ingest-types-special"
    title = "Specialized field types: date_nanos, unsigned_long, constant_keyword, version, dense_vector, sparse_vector"
    covers = ["ingest.types.date-nanos", "ingest.types.unsigned-long", "ingest.types.constant-keyword",
              "ingest.types.version", "ingest.types.dense-vector", "ingest.types.sparse-vector",
              "ingest.methods.document-apis"]

    def params(self, rnd, iid):
        return {"index": f"telemetry-{iid}", "env": rnd.choice(["prod", "staging", "edge"]),
                "dims": rnd.choice([3, 4, 5]), "similarity": rnd.choice(["cosine", "dot_product", "l2_norm"])}

    def doc(self, p):
        vec = [round(0.1 * (n + 1), 2) for n in range(p["dims"])]
        if p["similarity"] == "dot_product":
            norm = sum(v * v for v in vec) ** 0.5
            vec = [v / norm for v in vec]
        return {"event_time": "2026-05-01T12:30:45.123456789Z", "packets": 18446744073709551615,
                "env": p["env"], "agent_version": "8.17.10", "embedding": vec,
                "keywords": {"disk": 0.8, "latency": 1.7}}

    def prompt(self, ctx):
        p = ctx.p
        sim = {"cosine": "cosine similarity", "dot_product": "dot product (the vectors are unit length)",
               "l2_norm": "Euclidean (L2) distance"}[p["similarity"]]
        return f"""
Create the index `{p['index']}` with this mapping:

  event_time      a timestamp with nanosecond precision
  packets         a counter that can reach 2^64 - 1 (never negative)
  env             a field whose value is "{p['env']}" for every document of the index, set in
                  the mapping itself
  agent_version   software versions, so that a range query 8.9.0 to 8.17.10 orders them by
                  semantic version (8.10 after 8.9), not alphabetically
  embedding       a vector of {p['dims']} floats, indexed for kNN search with {sim}
  keywords        weighted terms ({{"disk": 0.8, "latency": 1.7}}) for sparse vector queries

Then index this document with the id 1:

  {json.dumps(self.doc(p))}
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "properties": {{
      "event_time": {{ "type": "date_nanos" }},
      "packets": {{ "type": "unsigned_long" }},
      "env": {{ "type": "constant_keyword", "value": "{p['env']}" }},
      "agent_version": {{ "type": "version" }},
      "embedding": {{ "type": "dense_vector", "dims": {p['dims']}, "index": true, "similarity": "{p['similarity']}" }},
      "keywords": {{ "type": "sparse_vector" }}
    }}
  }}
}}

PUT {p['index']}/_doc/1?refresh=true
{json.dumps(self.doc(p))}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = send(es, "HEAD", f"/{p['index']}")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return
        f = lambda name: field_mapping(es, p["index"], name) or {}
        c.equal(f("event_time").get("type"), "date_nanos", "event_time is date_nanos")
        c.equal(f("packets").get("type"), "unsigned_long", "packets is unsigned_long")
        e = f("env")
        c.check(e.get("type") == "constant_keyword" and e.get("value") == p["env"],
                f"env is a constant_keyword with the value {p['env']}", f"found {e}")
        c.equal(f("agent_version").get("type"), "version", "agent_version is a version field")
        v = f("embedding")
        c.check(v.get("type") == "dense_vector" and v.get("dims") == p["dims"] and v.get("index", True)
                and v.get("similarity", "cosine") == p["similarity"],
                f"embedding is an indexed dense_vector with {p['dims']} dims and {p['similarity']} similarity",
                f"found {v}")
        c.equal(f("keywords").get("type"), "sparse_vector", "keywords is a sparse_vector")
        status, response = send(es, "GET", f"/{p['index']}/_doc/1")
        c.check(status == 200 and get(response, "_source.packets") == 18446744073709551615,
                "document 1 is indexed")
        send(es, "POST", f"/{p['index']}/_refresh")
        status, response = send(es, "GET", f"/{p['index']}/_count", {"query": {"range": {
            "agent_version": {"gte": "8.9.0", "lte": "8.17.10"}}}})
        c.equal(get(response, "count"), 1, "a version range query from 8.9.0 to 8.17.10 finds the document")
