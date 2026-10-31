import json

from lib import nodes
from lib.tasklib import Task, field_mapping, index_settings

SOURCE_NODES = ["es-b1:9200", "es-b2:9200", "es-b3:9200"]
STATES = ["VA", "TX", "CA", "NY", "OH"]
CITIES = ["Richmond", "Austin", "Fresno", "Albany", "Dayton"]
REMOVED = ["member_number", "age", "gender"]


class RemoteTransformExam(Task):
    id = "ingest-remote-transform-exam"
    title = "Exam-style: move an index to another cluster with reindex from remote and transform it"
    covers = ["ingest.reindex.reindex-remote", "ingest.reindex.reindex-script", "ingest.mapping.param.fields",
              "ingest.mapping.param.ignore-above", "ingest.types.boolean", "ingest.types.numeric"]
    size = "exam"
    answer = "state"
    requires = ("shell", "cluster-b")

    def params(self, rnd, iid):
        docs = [{"member_number": i, "age": rnd.randint(18, 80), "gender": rnd.choice("FM"),
                 "firstname": f"name{i % 17}", "city": rnd.choice(CITIES), "state": rnd.choice(STATES),
                 "address": f"{rnd.randint(1, 900)} Main Street", "balance": rnd.randint(100, 50000)}
                for i in range(120)]
        return {"index": f"members-{iid}", "state": rnd.choice(STATES), "flag": rnd.choice(["tos_ack", "kyc_done"]),
                "above": rnd.choice([128, 256]), "docs": docs}

    def setup(self, ctx):
        p = ctx.p
        bulk = "".join('{"index":{}}\n' + json.dumps(d) + "\n" for d in p["docs"])
        ctx.es_b.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Move the index `{p['index']}` from cluster B to a new index of the same name on cluster A, with a
reindex from remote run on cluster A. (Cluster A must first be allowed to reach cluster B's HTTP
port and trust its certificate: static settings on every node of A, see `./ece config a1`, the CA
is at config/certs/ca/ca.crt, and restart the nodes one at a time. Login on B: elastic / elastic-lab.)

The new index has 1 primary and 0 replica shards, and:
  - doesn't contain the fields {', '.join(REMOVED)}
  - firstname, city and state are keyword fields
  - address is a text field with a keyword sub-field `raw` that indexes only the first {p['above']} characters
  - balance is a double
  - has a new boolean field {p['flag']}: false for members in the state {p['state']}, true for all others

When it's done, delete `{p['index']}` from cluster B.
"""

    def script(self, p):
        return (f"ctx._source.remove('member_number'); ctx._source.remove('age'); ctx._source.remove('gender'); "
                f"ctx._source.{p['flag']} = ctx._source.state != '{p['state']}'")

    def mapping(self, p):
        return {"settings": {"number_of_shards": 1, "number_of_replicas": 0}, "mappings": {"properties": {
            "firstname": {"type": "keyword"}, "city": {"type": "keyword"}, "state": {"type": "keyword"},
            "address": {"type": "text", "fields": {"raw": {"type": "keyword", "ignore_above": p["above"]}}},
            "balance": {"type": "double"}, p["flag"]: {"type": "boolean"}}}}

    def reindex(self, p):
        return {"source": {"remote": {"host": "https://es-b1:9200", "username": "elastic", "password": "elastic-lab"},
                           "index": p["index"]},
                "dest": {"index": p["index"]}, "script": {"source": self.script(p)}}

    def solution(self, ctx):
        p = ctx.p
        return f"""
# On es-a1, es-a2, es-a3 (./ece config a1 ...), add, then restart one at a time:
reindex.remote.whitelist: "{', '.join(SOURCE_NODES)}"
reindex.ssl.certificate_authorities: certs/ca/ca.crt

# On cluster A:
PUT {p['index']}
{json.dumps(self.mapping(p), indent=2)}

POST _reindex?refresh=true
{json.dumps(self.reindex(p), indent=2)}

# On cluster B:
DELETE {p['index']}
"""

    def apply_solution(self, ctx):
        p, es = ctx.p, ctx.es
        for node in nodes.CLUSTER_NODES["a"]:
            nodes.set_settings(node, {"reindex.remote.whitelist": f'"{", ".join(SOURCE_NODES)}"',
                                      "reindex.ssl.certificate_authorities": "certs/ca/ca.crt"})
            if not nodes.restart(node):
                return f"{node} didn't rejoin"
        es.put(f"/{p['index']}", self.mapping(p))
        status, response = es.send("POST", "/_reindex?refresh=true", json.dumps(self.reindex(p)).encode(),
                                   "application/json", timeout=300)
        if status != 200:
            return str(response)[:300]
        ctx.es_b.delete(f"/{p['index']}")
        return None

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        s = index_settings(es, p["index"])
        if not c.check(s is not None, f"index {p['index']} exists on cluster A"):
            return
        c.equal((s.get("index.number_of_shards"), s.get("index.number_of_replicas")), ("1", "0"), "1 primary, 0 replicas")
        es.send("POST", f"/{p['index']}/_refresh")
        c.equal(es.get(f"/{p['index']}/_count")["count"], len(p["docs"]), "all members are there")
        types = {f: (field_mapping(es, p["index"], f) or {}).get("type") for f in
                 ("firstname", "city", "state", "address", "balance", p["flag"])}
        c.equal(types, {"firstname": "keyword", "city": "keyword", "state": "keyword", "address": "text",
                        "balance": "double", p["flag"]: "boolean"}, "the field types")
        raw = field_mapping(es, p["index"], "address.raw") or {}
        c.equal((raw.get("type"), raw.get("ignore_above")), ("keyword", p["above"]), "address.raw")
        hits = es.post(f"/{p['index']}/_search", {"size": 200})["hits"]["hits"]
        left = sorted({f for h in hits for f in REMOVED if f in h["_source"]})
        c.check(not left, "the removed fields are gone from the documents", f"still there: {left}")
        false_count = es.post(f"/{p['index']}/_count", {"query": {"term": {p["flag"]: False}}})["count"]
        want = sum(d["state"] == p["state"] for d in p["docs"])
        c.equal(false_count, want, f"{p['flag']} is false exactly for members in {p['state']}")
        c.check(ctx.es_b.send("HEAD", f"/{p['index']}")[0] == 404, f"{p['index']} is deleted from cluster B")

    def cleanup(self, ctx):
        for node in nodes.CLUSTER_NODES["a"]:
            nodes.restore(node)
