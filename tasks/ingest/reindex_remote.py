import json

from lib import nodes
from lib.tasklib import Task

SOURCE_NODES = ["es-b1:9200", "es-b2:9200", "es-b3:9200"]


class ReindexRemote(Task):
    id = "ingest-reindex-remote"
    title = "Reindex from a remote cluster (whitelist and TLS on the destination)"
    covers = ["ingest.reindex.reindex-remote", "cluster.maintenance.node-settings", "ingest.reindex.reindex-query"]
    size = "exam"
    answer = "state"
    requires = ("shell", "cluster-b")

    def params(self, rnd, iid):
        return {"source": f"legacy-orders-{iid}", "dest": f"orders-migrated-{iid}", "docs": rnd.randint(80, 200),
                "min_total": rnd.choice([50, 100]), "host": rnd.choice(["es-b1", "es-b2"])}

    def setup(self, ctx):
        p = ctx.p
        bulk = "".join('{"index":{}}\n' + json.dumps({"order": i, "total": (i * 37) % 250}) + "\n"
                       for i in range(p["docs"]))
        ctx.es_b.send("POST", f"/{p['source']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def expected(self, p):
        return sum(1 for i in range(p["docs"]) if (i * 37) % 250 >= p["min_total"])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Copy the orders with a total of {p['min_total']} or more from the index `{p['source']}` on cluster B
into the new index `{p['dest']}` on cluster A, with a reindex from remote run on cluster A.

Cluster A must be allowed to connect to cluster B's HTTP port ({p['host']}:9200) for reindexing, and
it must trust cluster B's certificate (signed by the lab's CA, which is at config/certs/ca/ca.crt
on every node). These are static node settings: change elasticsearch.yml on every node of cluster A
(`./ece config a1` ...) and restart them one at a time (`./ece restart a1` ...).
Use the elastic user of cluster B (password elastic-lab) for the remote connection.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# On es-a1, es-a2 and es-a3 (./ece config a1 ...), add:
reindex.remote.whitelist: "{', '.join(SOURCE_NODES)}"
reindex.ssl.certificate_authorities: certs/ca/ca.crt
# and restart them one at a time: ./ece restart a1, a2, a3

POST _reindex
{{
  "source": {{
    "remote": {{
      "host": "https://{p['host']}:9200",
      "username": "elastic",
      "password": "elastic-lab"
    }},
    "index": "{p['source']}",
    "query": {{ "range": {{ "total": {{ "gte": {p['min_total']} }} }} }}
  }},
  "dest": {{ "index": "{p['dest']}" }}
}}
"""

    def apply_solution(self, ctx):
        p = ctx.p
        for node in nodes.CLUSTER_NODES["a"]:
            nodes.set_settings(node, {"reindex.remote.whitelist": f'"{", ".join(SOURCE_NODES)}"',
                                      "reindex.ssl.certificate_authorities": "certs/ca/ca.crt"})
            if not nodes.restart(node):
                return f"{node} didn't rejoin"
        body = {"source": {"remote": {"host": f"https://{p['host']}:9200", "username": "elastic",
                                      "password": "elastic-lab"},
                           "index": p["source"], "query": {"range": {"total": {"gte": p["min_total"]}}}},
                "dest": {"index": p["dest"]}}
        status, response = ctx.es.send("POST", "/_reindex?refresh=true", json.dumps(body).encode(),
                                       "application/json", timeout=300)
        return None if status == 200 else str(response)[:300]

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/{p['dest']}/_count")
        if not c.check(status == 200, f"index {p['dest']} exists on cluster A"):
            return
        c.equal(response.get("count"), self.expected(p), f"it holds the {self.expected(p)} orders with total >= {p['min_total']}")

    def cleanup(self, ctx):
        for node in nodes.CLUSTER_NODES["a"]:
            nodes.restore(node)
