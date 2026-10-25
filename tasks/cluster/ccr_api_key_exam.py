import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, exists, get  # noqa: E402


class CcrApiKeyExam(Task):
    id = "cluster-ccr-api-key-exam"
    title = "Exam-style: API key remote cluster, follower index and auto-follow pattern"
    covers = ["cluster.remote.api-key-model", "cluster.remote.settings", "cluster.ccr.follower",
              "cluster.ccr.auto-follow", "cluster.remote.remote-info", "search.ccs.search"]
    size = "exam"
    answer = "state"
    cluster = "b"
    requires = ("shell", "cluster-b")

    def params(self, rnd, iid):
        app = rnd.choice(["crm", "erp", "hr"])
        return {"alias": f"{rnd.choice(['leader', 'primary_dc', 'site_a'])}_{iid}", "key": f"ccr-{iid}",
                "prefix": f"{app}-{iid}", "existing": f"{app}-{iid}-contacts", "private": f"vault-{iid}",
                "node": rnd.choice(["es-a1", "es-a2", "es-a3"]), "pattern": f"{app}-{iid}-all",
                "docs": rnd.choice([40, 60, 90])}

    def setup(self, ctx):
        p = ctx.p
        h.bulk(ctx.es_a, p["existing"], h.sales_docs(ctx.iid, "a", p["docs"]), h.SALES_MAPPING)
        h.bulk(ctx.es_a, p["private"], h.sales_docs(ctx.iid, "a", 5), h.SALES_MAPPING)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster B becomes the standby site for cluster A's `{p['prefix']}-*` indices. The clusters must
connect with the API key security model (the remote cluster server listens on port 9443 with
TLS on every node), and cluster B may only see these indices of cluster A.

  1. On cluster A, create a cross-cluster API key `{p['key']}` that allows both searching and
     replicating `{p['prefix']}-*`, and nothing else.
  2. On every node of cluster B, store its encoded value in the keystore as
     `cluster.remote.{p['alias']}.credentials` (`./ece shell b1`, b2, b3, then
     bin/elasticsearch-keystore), and load it without restarting the nodes.
  3. On cluster B, add the persistent remote cluster `{p['alias']}` in proxy mode through
     {p['node']}:9443.
  4. On cluster B, replicate `{p['existing']}` into a follower index of the same name.
  5. On cluster B, create the auto-follow pattern `{p['pattern']}` so that every new
     `{p['prefix']}-*` index on cluster A is replicated into a follower of the same name.

Afterwards, cluster B must not be able to replicate or search `{p['private']}` on cluster A.
"""

    def solution(self, ctx):
        p = ctx.p
        text = f"""
# On cluster A
POST _security/cross_cluster/api_key
{{
  "name": "{p['key']}",
  "access": {{
    "search": [ {{ "names": ["{p['prefix']}-*"] }} ],
    "replication": [ {{ "names": ["{p['prefix']}-*"] }} ]
  }}
}}

# Shell, on es-b1, es-b2 and es-b3 (./ece shell b1 ...): store the "encoded" value of the
# response; the command prompts for it.
#   bin/elasticsearch-keystore add cluster.remote.{p['alias']}.credentials

# On cluster B
POST _nodes/reload_secure_settings

PUT _cluster/settings
{{
  "persistent": {{
    "cluster.remote.{p['alias']}.mode": "proxy",
    "cluster.remote.{p['alias']}.proxy_address": "{p['node']}:9443"
  }}
}}

PUT {p['existing']}/_ccr/follow?wait_for_active_shards=1
{{
  "remote_cluster": "{p['alias']}",
  "leader_index": "{p['existing']}"
}}

PUT _ccr/auto_follow/{p['pattern']}
{{
  "remote_cluster": "{p['alias']}",
  "leader_index_patterns": ["{p['prefix']}-*"],
  "follow_index_pattern": "{{{{leader_index}}}}"
}}
"""
        return text

    def apply_solution(self, ctx):
        text = self.solution(ctx)
        (_, a_text), (_, b_text) = h.blocks(text)
        results = h.run_block("a", a_text)
        h.keystore_add("b", f"cluster.remote.{ctx.p['alias']}.credentials", results[0][2]["encoded"])
        h.run_block("b", b_text)

    def verify(self, ctx, c):
        p, a, b = ctx.p, ctx.es_a, ctx.es_b
        status, response = h.send(a, "GET", f"/_security/api_key?name={p['key']}&active_only=true")
        keys = (response or {}).get("api_keys", []) if status == 200 else []
        c.check(keys and keys[0].get("type") == "cross_cluster",
                f"cluster A has an active cross-cluster API key {p['key']}", str(keys)[:200])
        persistent, _ = h.remote_settings(b, p["alias"])
        c.check(persistent.get("mode") == "proxy" and persistent.get("proxy_address") == f"{p['node']}:9443",
                f"{p['alias']} is a persistent proxy-mode remote through {p['node']}:9443", str(persistent))
        h.wait_connected(b, p["alias"], 10)
        info = h.send(b, "GET", "/_remote/info")[1] or {}
        c.check(get(info, f"{p['alias']}.cluster_credentials"), f"{p['alias']} uses API key credentials",
                "no credentials loaded: check the keystore on all nodes of cluster B and reload the secure settings")
        if not c.check(get(info, f"{p['alias']}.connected"), f"{p['alias']} is connected"):
            return
        follow = h.follow_info(b, p["existing"])
        c.check(follow and follow.get("remote_cluster") == p["alias"] and follow.get("status") == "active",
                f"{p['existing']} on cluster B follows {p['alias']}:{p['existing']}", str(follow)[:200])
        c.check(h.wait_for(lambda: h.count(b, p["existing"]) == p["docs"], 15),
                "the follower has all documents")
        status, response = h.send(b, "GET", f"/{p['alias']}:{p['existing']}/_count")
        c.check(status == 200 and response.get("count") == p["docs"],
                f"cluster B can search {p['alias']}:{p['existing']}", str(response)[:200])
        status, _ = h.send(b, "GET", f"/_ccr/auto_follow/{p['pattern']}")
        if c.check(status == 200, f"auto-follow pattern {p['pattern']} exists"):
            new = f"{p['prefix']}-new{int(time.time())}"
            h.send(a, "PUT", f"/{new}", {"settings": {"number_of_shards": 1, "number_of_replicas": 0}})
            c.check(h.wait_for(lambda: exists(b, f"/{new}") and h.follow_info(b, new), 30),
                    f"a new index {new} on cluster A is followed on cluster B under the same name")
        probe = f"{p['private']}-probe"
        status, _ = h.send(b, "PUT", f"/{probe}/_ccr/follow?wait_for_active_shards=1",
                           {"remote_cluster": p["alias"], "leader_index": p["private"]})
        h.send(b, "DELETE", f"/{probe}")
        c.check(status >= 400, f"cluster B can't replicate {p['private']}", f"HTTP {status}")
        status, response = h.send(b, "GET", f"/{p['alias']}:{p['private']}/_search?size=0")
        c.check(status >= 400 or not get(response, "hits.total.value"), f"cluster B can't search {p['private']}",
                str(response)[:200])

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid, keystore=True, api_keys=True)
