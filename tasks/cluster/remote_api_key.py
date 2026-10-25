import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.sampledata import ECOMMERCE, FLIGHT_CARRIERS, FLIGHTS  # noqa: E402
from lib.tasklib import Task, get  # noqa: E402


class RemoteApiKey(Task):
    id = "cluster-remote-api-key"
    title = "Connect a remote cluster with a cross-cluster API key that limits what can be searched"
    covers = ["cluster.remote.api-key-model", "cluster.remote.settings", "cluster.remote.remote-info",
              "search.ccs.search"]
    size = "exam"
    answer = "state"
    requires = ("shell", "cluster-b")

    def params(self, rnd, iid):
        return {"alias": f"{rnd.choice(['secure_b', 'partner', 'dc2'])}_{iid}", "key": f"ccs-{iid}",
                "carrier": rnd.choice(FLIGHT_CARRIERS), "node": rnd.choice(["es-b1", "es-b2", "es-b3"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Connect cluster A to cluster B with the API key security model. Every node of both clusters
already runs the remote cluster server on port 9443 with TLS (trusted by the shared CA).

  1. On cluster B, create a cross-cluster API key named `{p['key']}` that only allows searching
     `{FLIGHTS}`, and only its documents whose Carrier is "{p['carrier']}".
  2. On every node of cluster A, store the key's encoded value in the Elasticsearch keystore as
     the secure setting `cluster.remote.{p['alias']}.credentials` (open a shell with
     `./ece shell a1`, a2, a3, and use bin/elasticsearch-keystore), then make the nodes load it
     without restarting them.
  3. On cluster A, add the persistent remote cluster `{p['alias']}` in proxy mode, connecting
     through {p['node']}:9443.

From cluster A, GET {p['alias']}:{FLIGHTS}/_count must then return only the {p['carrier']} flights,
and searching {p['alias']}:{ECOMMERCE} must be refused.
"""

    def solution(self, ctx):
        p = ctx.p
        text = f"""
# On cluster B
POST _security/cross_cluster/api_key
{{
  "name": "{p['key']}",
  "access": {{
    "search": [
      {{
        "names": ["{FLIGHTS}"],
        "query": {{ "term": {{ "Carrier": "{p['carrier']}" }} }}
      }}
    ]
  }}
}}

# Shell, on es-a1, es-a2 and es-a3 (./ece shell a1 ...): store the "encoded" value of the
# response; the command prompts for it.
#   bin/elasticsearch-keystore add cluster.remote.{p['alias']}.credentials

# On cluster A
POST _nodes/reload_secure_settings

PUT _cluster/settings
{{
  "persistent": {{
    "cluster.remote.{p['alias']}.mode": "proxy",
    "cluster.remote.{p['alias']}.proxy_address": "{p['node']}:9443"
  }}
}}

GET _remote/info
GET {p['alias']}:{FLIGHTS}/_count
"""
        return text

    def apply_solution(self, ctx):
        text = self.solution(ctx)
        (_, b_text), (_, a_text) = h.blocks(text)
        results = h.run_block("b", b_text)
        encoded = results[0][2]["encoded"]
        h.keystore_add("a", f"cluster.remote.{ctx.p['alias']}.credentials", encoded)
        h.run_block("a", a_text)

    def verify(self, ctx, c):
        p, a, b = ctx.p, ctx.es_a, ctx.es_b
        status, response = h.send(b, "GET", f"/_security/api_key?name={p['key']}&active_only=true")
        keys = (response or {}).get("api_keys", []) if status == 200 else []
        c.check(keys and keys[0].get("type") == "cross_cluster",
                f"cluster B has an active cross-cluster API key {p['key']}", str(keys)[:200])
        persistent, _ = h.remote_settings(a, p["alias"])
        c.check(persistent.get("mode") == "proxy" and persistent.get("proxy_address") == f"{p['node']}:9443",
                f"{p['alias']} is a persistent proxy-mode remote through {p['node']}:9443", str(persistent))
        h.wait_connected(a, p["alias"], 10)
        info = h.send(a, "GET", "/_remote/info")[1] or {}
        c.check(get(info, f"{p['alias']}.cluster_credentials"), f"{p['alias']} uses API key credentials",
                "no credentials loaded: check the keystore on all nodes and reload the secure settings")
        c.check(get(info, f"{p['alias']}.connected"), f"{p['alias']} is connected")
        want = h.send(b, "GET", f"/{FLIGHTS}/_count", {"query": {"term": {"Carrier": p["carrier"]}}})[1]["count"]
        status, response = h.send(a, "GET", f"/{p['alias']}:{FLIGHTS}/_count")
        c.check(status == 200 and response.get("count") == want,
                f"{p['alias']}:{FLIGHTS} shows only the {want} {p['carrier']} flights",
                f"HTTP {status}: {str(response)[:200]}")
        status, response = h.send(a, "GET", f"/{p['alias']}:{ECOMMERCE}/_search?size=0")
        refused = status >= 400 or not get(response, "hits.total.value")
        c.check(refused, f"{p['alias']}:{ECOMMERCE} can't be searched", str(response)[:200])

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid, keystore=True, api_keys=True)
