import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get  # noqa: E402


class SnapshotIndices(Task):
    id = "cluster-snapshot-indices"
    title = "Register a file system repository and snapshot specific indices"
    covers = ["cluster.snapshots.fs-repository", "cluster.snapshots.create", "cluster.snapshots.monitor-delete"]
    answer = "state"

    def params(self, rnd, iid):
        names = ["products", "orders", "customers", "invoices"]
        rnd.shuffle(names)
        return {
            "repo": f"backup-{iid}", "location": f"a/backup-{iid}",
            "legacy": f"legacy-{iid}", "legacy_location": f"a/legacy-{iid}",
            "indices": [f"{n}-{iid}" for n in names[:3]], "chosen": sorted(f"{n}-{iid}" for n in names[:2]),
            "snapshot": rnd.choice(["weekly-1", "before-upgrade", "baseline", "snap-001"]),
            "rate": rnd.choice(["20mb", "50mb", "100mb"]),
            "owner": rnd.choice(["ops-team", "dba", "platform"]),
            "drop": rnd.choice(["legacy-snap-1", "legacy-snap-2"]),
        }

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for i, index in enumerate(p["indices"]):
            h.bulk(es, index, h.sales_docs(f"{ctx.iid}{i}", "a", 50), h.SALES_MAPPING)
        h.must(es, "PUT", f"/_snapshot/{p['legacy']}", {"type": "fs", "settings": {"location": p["legacy_location"]}})
        for snap in ("legacy-snap-1", "legacy-snap-2"):
            h.must(es, "PUT", f"/_snapshot/{p['legacy']}/{snap}?wait_for_completion=true",
                   {"indices": p["indices"][2], "include_global_state": False})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster A's nodes have `path.repo` set to /usr/share/elasticsearch/snapshots.

  1. Register a shared file system repository `{p['repo']}` with the location "{p['location']}"
     (relative to path.repo). Limit snapshot speed to {p['rate']} per second per node.
  2. Create the snapshot `{p['snapshot']}` in it that contains only the indices
     {' and '.join(f'`{i}`' for i in p['chosen'])}, without the cluster's global state, and with the
     metadata field "taken_by" set to "{p['owner']}". Make sure it completed successfully.
  3. The repository `{p['legacy']}` holds two old snapshots. Delete `{p['drop']}` and keep the other.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _snapshot/{p['repo']}
{{
  "type": "fs",
  "settings": {{
    "location": "{p['location']}",
    "max_snapshot_bytes_per_sec": "{p['rate']}"
  }}
}}

PUT _snapshot/{p['repo']}/{p['snapshot']}?wait_for_completion=true
{{
  "indices": "{','.join(p['chosen'])}",
  "include_global_state": false,
  "metadata": {{ "taken_by": "{p['owner']}" }}
}}

GET _snapshot/{p['repo']}/{p['snapshot']}

GET _snapshot/{p['legacy']}/_all
DELETE _snapshot/{p['legacy']}/{p['drop']}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        repo = h.repository(es, p["repo"])
        if c.check(repo, f"repository {p['repo']} exists"):
            c.equal(repo.get("type"), "fs", "it is a shared file system repository")
            c.check(h.location_matches(repo, p["location"]), f"its location is {p['location']}",
                    f"found {get(repo, 'settings.location')}")
            c.equal(get(repo, "settings.max_snapshot_bytes_per_sec"), p["rate"], f"snapshots are limited to {p['rate']}/s")
        snap = h.snapshot_info(es, p["repo"], p["snapshot"])
        if c.check(snap, f"snapshot {p['snapshot']} exists in {p['repo']}"):
            c.equal(snap.get("state"), "SUCCESS", "the snapshot completed successfully")
            c.equal(sorted(snap.get("indices", [])), p["chosen"], "it contains exactly the requested indices")
            c.equal(snap.get("include_global_state"), False, "it doesn't include the global state")
            c.equal(get(snap, "metadata.taken_by"), p["owner"], "its metadata has taken_by")
        status, response = h.send(es, "GET", f"/_snapshot/{p['legacy']}/_all")
        names = sorted(s["snapshot"] for s in (response or {}).get("snapshots", [])) if status == 200 else None
        keep = "legacy-snap-2" if p["drop"] == "legacy-snap-1" else "legacy-snap-1"
        c.equal(names, [keep], f"{p['legacy']} only holds {keep}")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid, snapshots=True)
