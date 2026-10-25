import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, exists, index_settings  # noqa: E402


class SearchableSnapshot(Task):
    id = "cluster-searchable-snapshot"
    title = "Archive an index as a fully mounted searchable snapshot"
    covers = ["cluster.snapshots.searchable-snapshot", "cluster.snapshots.create", "cluster.snapshots.fs-repository"]
    answer = "state"

    def params(self, rnd, iid):
        month = rnd.choice(["2026.06", "2026.07", "2026.08"])
        return {
            "repo": f"cold-{iid}", "location": f"a/cold-{iid}", "index": f"applogs-{iid}-{month}",
            "snapshot": f"applogs-{month}", "mounted": f"applogs-{iid}-{month}-archive",
            "docs": rnd.choice([60, 90, 120]), "tier": rnd.choice(["data_cold", "data_warm"]),
        }

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        h.bulk(es, p["index"], h.sales_docs(ctx.iid, "a", p["docs"]), h.SALES_MAPPING)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
On cluster A, the index `{p['index']}` is no longer written to, and should be kept searchable at
a lower cost using a searchable snapshot.

  1. Register the shared file system repository `{p['repo']}` at "{p['location']}" (relative to
     path.repo), and snapshot `{p['index']}` into it as `{p['snapshot']}` (only this index).
  2. Mount the index from that snapshot as a fully mounted index (a full local copy) named
     `{p['mounted']}`, with no replicas and with the tier preference "{p['tier']}".
  3. Delete the original index `{p['index']}`. All its documents must stay searchable in
     `{p['mounted']}`.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _snapshot/{p['repo']}
{{
  "type": "fs",
  "settings": {{ "location": "{p['location']}" }}
}}

PUT _snapshot/{p['repo']}/{p['snapshot']}?wait_for_completion=true
{{
  "indices": "{p['index']}",
  "include_global_state": false
}}

POST _snapshot/{p['repo']}/{p['snapshot']}/_mount?wait_for_completion=true&storage=full_copy
{{
  "index": "{p['index']}",
  "renamed_index": "{p['mounted']}",
  "index_settings": {{
    "index.number_of_replicas": 0,
    "index.routing.allocation.include._tier_preference": "{p['tier']}"
  }}
}}

DELETE {p['index']}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        settings = index_settings(es, p["mounted"])
        if c.check(settings, f"{p['mounted']} exists"):
            c.equal(settings.get("index.store.type"), "snapshot", "it is a searchable snapshot (mounted) index")
            c.equal(settings.get("index.store.snapshot.repository_name"), p["repo"], f"it is mounted from {p['repo']}")
            c.equal(settings.get("index.store.snapshot.snapshot_name"), p["snapshot"], f"from snapshot {p['snapshot']}")
            c.check(settings.get("index.store.snapshot.partial") in (None, "false"),
                    "it is fully mounted (full_copy)", "it is partially mounted")
            c.equal(settings.get("index.number_of_replicas"), "0", "it has no replicas")
            c.equal(settings.get("index.routing.allocation.include._tier_preference"), p["tier"],
                    f"its tier preference is {p['tier']}")
            c.equal(h.wait_for(lambda: h.count(es, p["mounted"]), seconds=15), p["docs"],
                    "all documents are searchable")
        c.check(not exists(es, f"/{p['index']}"), f"the original index {p['index']} was deleted")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid, snapshots=True)
