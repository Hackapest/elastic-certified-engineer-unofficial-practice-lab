import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get, index_settings  # noqa: E402


class SnapshotOtherCluster(Task):
    id = "cluster-snapshot-other-cluster"
    title = "Restore a snapshot taken on cluster A on cluster B through a read-only repository"
    covers = ["cluster.snapshots.restore-other-cluster", "cluster.snapshots.fs-repository",
              "cluster.snapshots.restore", "cluster.snapshots.restore-rename"]
    answer = "state"
    cluster = "b"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        return {
            "repo_a": f"transfer-{iid}", "repo_b": f"from-a-{iid}", "location": f"shared/transfer-{iid}",
            "snapshot": rnd.choice(["export-1", "migration", "handover"]),
            "index": f"{rnd.choice(['catalog', 'inventory', 'pricing'])}-{iid}",
            "docs": rnd.choice([70, 110, 150]), "replicas": rnd.choice([0, 1]),
            "suffix": rnd.choice(["from-a", "migrated", "imported"]),
        }

    def target(self, p):
        return f"{p['index']}-{p['suffix']}"

    def setup(self, ctx):
        p, a = ctx.p, ctx.es_a
        h.bulk(a, p["index"], h.sales_docs(ctx.iid, "a", p["docs"]), h.SALES_MAPPING)
        h.must(a, "PUT", f"/_snapshot/{p['repo_a']}", {"type": "fs", "settings": {"location": p["location"]}})
        h.must(a, "PUT", f"/_snapshot/{p['repo_a']}/{p['snapshot']}?wait_for_completion=true",
               {"indices": p["index"], "include_global_state": False})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster A wrote the snapshot `{p['snapshot']}` of the index `{p['index']}` to its repository
`{p['repo_a']}`, located at "{p['location']}" under path.repo. Cluster B's nodes mount the same
directory at the same path.repo.

On cluster B:

  1. Register that location as the repository `{p['repo_b']}`, so that cluster B can never
     write to it (cluster A remains the only writer).
  2. Restore `{p['index']}` from `{p['snapshot']}` as `{self.target(p)}`, with
     {p['replicas']} replica(s).

Don't change anything on cluster A.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# On cluster B
PUT _snapshot/{p['repo_b']}
{{
  "type": "fs",
  "settings": {{
    "location": "{p['location']}",
    "readonly": true
  }}
}}

GET _snapshot/{p['repo_b']}/_all

POST _snapshot/{p['repo_b']}/{p['snapshot']}/_restore?wait_for_completion=true
{{
  "indices": "{p['index']}",
  "include_global_state": false,
  "rename_pattern": "(.+)",
  "rename_replacement": "$1-{p['suffix']}",
  "index_settings": {{ "index.number_of_replicas": {p['replicas']} }}
}}
"""

    def verify(self, ctx, c):
        p, b = ctx.p, ctx.es_b
        repo = h.repository(b, p["repo_b"])
        if c.check(repo, f"repository {p['repo_b']} exists on cluster B"):
            c.check(repo.get("type") == "fs" and h.location_matches(repo, p["location"]),
                    f"it points to {p['location']}", str(repo)[:200])
            c.equal(str(get(repo, "settings.readonly")).lower(), "true", "it is read-only")
        settings = index_settings(b, self.target(p))
        if c.check(settings, f"{self.target(p)} exists on cluster B"):
            c.equal(h.count(b, self.target(p)), p["docs"], "it has all documents")
            c.equal(settings.get("index.number_of_replicas"), str(p["replicas"]), f"it has {p['replicas']} replica(s)")
        snap = h.snapshot_info(ctx.es_a, p["repo_a"], p["snapshot"])
        c.check(snap and snap.get("state") == "SUCCESS", "the snapshot is still intact in cluster A's repository")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid, snapshots=True)
