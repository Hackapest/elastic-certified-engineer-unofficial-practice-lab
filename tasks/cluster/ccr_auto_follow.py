import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, exists, get, index_settings  # noqa: E402


class CcrAutoFollow(Task):
    id = "cluster-ccr-auto-follow"
    title = "Follow new indices automatically with an auto-follow pattern"
    covers = ["cluster.ccr.auto-follow", "cluster.ccr.follower"]
    answer = "state"
    cluster = "b"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        base = rnd.choice(["events", "audit", "clicks"])
        return {"alias": f"{rnd.choice(['cluster_a', 'origin', 'hq'])}_{iid}", "base": f"{base}-{iid}",
                "pattern": f"{base}-{iid}", "suffix": rnd.choice(["copy", "mirror", "dr"]),
                "existing": f"{base}-{iid}-2026.10.01", "exclude": rnd.choice(["test", "tmp", "debug"])}

    def follower_name(self, p, leader):
        return f"{leader}-{p['suffix']}"

    def setup(self, ctx):
        p = ctx.p
        h.bulk(ctx.es_a, p["existing"], h.sales_docs(ctx.iid, "a", 30), h.SALES_MAPPING)
        h.set_remote(ctx.es_b, p["alias"], [h.TRANSPORT_SEED["a"]])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster A creates a new index `{p['base']}-<date>` every day. Cluster A is configured on
cluster B as the remote cluster `{p['alias']}`.

On cluster B:
  1. Create the auto-follow pattern `{p['pattern']}` so that every new index on cluster A whose
     name starts with "{p['base']}-" is replicated automatically into a follower named after the
     leader index plus "-{p['suffix']}" (e.g. `{self.follower_name(p, p['existing'])}`).
     Indices starting with "{p['base']}-{p['exclude']}" must not be replicated. The followers
     must have no replicas.
  2. The existing index `{p['existing']}` isn't picked up by the pattern. Replicate it as well,
     into a follower with the same naming convention.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# On cluster B
PUT _ccr/auto_follow/{p['pattern']}
{{
  "remote_cluster": "{p['alias']}",
  "leader_index_patterns": ["{p['base']}-*"],
  "leader_index_exclusion_patterns": ["{p['base']}-{p['exclude']}*"],
  "follow_index_pattern": "{{{{leader_index}}}}-{p['suffix']}",
  "settings": {{ "index.number_of_replicas": 0 }}
}}

PUT {self.follower_name(p, p['existing'])}/_ccr/follow?wait_for_active_shards=1
{{
  "remote_cluster": "{p['alias']}",
  "leader_index": "{p['existing']}"
}}
"""

    def verify(self, ctx, c):
        p, a, b = ctx.p, ctx.es_a, ctx.es_b
        status, response = h.send(b, "GET", f"/_ccr/auto_follow/{p['pattern']}")
        c.check(status == 200, f"auto-follow pattern {p['pattern']} exists")
        existing = self.follower_name(p, p["existing"])
        info = h.follow_info(b, existing)
        c.check(info and info.get("leader_index") == p["existing"] and info.get("status") == "active",
                f"{existing} follows {p['existing']}", str(info)[:200])
        if status != 200:
            return
        stamp = int(time.time())
        new, excluded = f"{p['base']}-2026.11.{stamp}", f"{p['base']}-{p['exclude']}-{stamp}"
        for index in (new, excluded):
            h.send(a, "PUT", f"/{index}", {"settings": {"number_of_shards": 1, "number_of_replicas": 0}})
            h.send(a, "POST", f"/{index}/_doc?refresh=true", {"store": "x"})
        follower = self.follower_name(p, new)
        followed = h.wait_for(lambda: exists(b, f"/{follower}"), 30)
        if c.check(followed, f"a new index {new} on cluster A is followed as {follower}"):
            c.equal(get(h.follow_info(b, follower) or {}, "remote_cluster"), p["alias"], f"through {p['alias']}")
            c.equal((index_settings(b, follower) or {}).get("index.number_of_replicas"), "0",
                    "the follower has no replicas")
        status, resolved = h.send(b, "GET", f"/_resolve/index/{p['base']}-{p['exclude']}*")
        c.check(status == 200 and not resolved.get("indices"), f"indices starting with {p['base']}-{p['exclude']} are not followed",
                str(resolved)[:200])

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
