import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib import client  # noqa: E402
from lib.tasklib import Task, short_error  # noqa: E402


class CcrPrivileges(Task):
    id = "cluster-ccr-privileges"
    title = "Roles for a user that sets up cross-cluster replication"
    covers = ["cluster.ccr.privileges", "cluster.ccr.follower"]
    answer = "state"
    cluster = "b"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        base = rnd.choice(["ledger", "payroll", "assets"])
        return {"alias": f"cluster_a_{iid}", "base": f"{base}-{iid}", "role": f"ccr-{base}-{iid}",
                "user": f"replicator-{iid}", "password": f"repl-{iid}-{rnd.randrange(1000, 9999)}",
                "private": f"private-{iid}"}

    def setup(self, ctx):
        p = ctx.p
        h.bulk(ctx.es_a, f"{p['base']}-2026", h.sales_docs(ctx.iid, "a", 20), h.SALES_MAPPING)
        h.bulk(ctx.es_a, p["private"], h.sales_docs(ctx.iid, "a", 5), h.SALES_MAPPING)
        h.set_remote(ctx.es_b, p["alias"], [h.TRANSPORT_SEED["a"]])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster A (the leader cluster) is configured on cluster B (the follower cluster) as the remote
cluster `{p['alias']}`, with the certificate-based security model. Replication must be run by a
dedicated user on cluster B instead of `elastic`.

  1. Create a role named `{p['role']}` on both clusters, with the least privileges needed for
     the user to create and manage follower indices on cluster B for the leader indices
     `{p['base']}-*` on cluster A, followers also named `{p['base']}-*`. On cluster A the role
     grants what the leader side needs; on cluster B what the follower side needs.
  2. On cluster B, create the user `{p['user']}` with the password "{p['password']}" and the role
     `{p['role']}`.

The user must be able to create a follower of `{p['base']}-2026` on cluster B, but must not be
able to replicate other indices of cluster A, such as `{p['private']}`.
"""

    def solution(self, ctx):
        p = ctx.p
        text = f"""
# On cluster A
PUT _security/role/{p['role']}
{{
  "cluster": ["read_ccr"],
  "indices": [
    {{ "names": ["{p['base']}-*"], "privileges": ["monitor", "read"] }}
  ]
}}

# On cluster B
PUT _security/role/{p['role']}
{{
  "cluster": ["manage_ccr"],
  "indices": [
    {{ "names": ["{p['base']}-*"], "privileges": ["monitor", "read", "write", "manage_follow_index"] }}
  ]
}}

PUT _security/user/{p['user']}
{{
  "password": "{p['password']}",
  "roles": ["{p['role']}"]
}}
"""
        return text

    def apply_solution(self, ctx):
        text = self.solution(ctx)
        h.run_blocks(text)

    def verify(self, ctx, c):
        p, b = ctx.p, ctx.es_b
        status, _ = h.send(b, "GET", f"/_security/user/{p['user']}")
        if not c.check(status == 200, f"user {p['user']} exists on cluster B"):
            return
        user = client.es("b", user=p["user"], password=p["password"])
        status, response = h.send(user, "GET", "/_security/_authenticate")
        if not c.check(status == 200, f"{p['user']} can log in with the given password", short_error(response)):
            return
        stamp = int(time.time())
        follower = f"{p['base']}-check-{stamp}"
        status, response = h.send(user, "PUT", f"/{follower}/_ccr/follow?wait_for_active_shards=1",
                                  {"remote_cluster": p["alias"], "leader_index": f"{p['base']}-2026"})
        c.check(status == 200, f"{p['user']} can create a follower of {p['base']}-2026", short_error(response))
        if status == 200:
            synced = h.wait_for(lambda: h.count(b, follower) == 20, 15)
            c.check(synced, "the follower replicates the leader's documents")
            status, response = h.send(user, "POST", f"/{follower}/_ccr/pause_follow")
            c.check(status == 200, f"{p['user']} can manage (pause) the follower", short_error(response))
        h.send(b, "DELETE", f"/{follower}")
        other = f"{p['base']}-private-{stamp}"
        status, _ = h.send(user, "PUT", f"/{other}/_ccr/follow?wait_for_active_shards=1",
                           {"remote_cluster": p["alias"], "leader_index": p["private"]})
        c.check(status == 403, f"{p['user']} can't replicate {p['private']}", f"HTTP {status}")
        h.send(b, "DELETE", f"/{other}")
        status, _ = h.send(user, "PUT", f"/{p['base']}-scratch-{stamp}", {})
        h.send(b, "DELETE", f"/{p['base']}-scratch-{stamp}")
        c.check(status == 403, f"{p['user']} can't create regular indices (least privilege)", f"HTTP {status}")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
