import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task  # noqa: E402


class SnapshotClone(Task):
    id = "cluster-snapshot-clone"
    title = "Clone part of a snapshot, then delete the original"
    covers = ["cluster.snapshots.clone", "cluster.snapshots.monitor-delete", "cluster.snapshots.verify-cleanup"]
    answer = "state"

    def params(self, rnd, iid):
        kinds = ["hr", "finance", "sales", "support"]
        rnd.shuffle(kinds)
        return {
            "repo": f"vault-{iid}", "location": f"a/vault-{iid}", "source": "full-2026.10.01",
            "indices": [f"{k}-{iid}" for k in kinds], "keep": sorted(f"{k}-{iid}" for k in kinds[:2]),
            "clone": rnd.choice(["legal-hold", "keep-forever", "audit-copy"]),
        }

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for i, index in enumerate(p["indices"]):
            h.bulk(es, index, h.sales_docs(f"{ctx.iid}{i}", "a", 20), h.SALES_MAPPING)
        h.must(es, "PUT", f"/_snapshot/{p['repo']}", {"type": "fs", "settings": {"location": p["location"]}})
        h.must(es, "PUT", f"/_snapshot/{p['repo']}/{p['source']}?wait_for_completion=true",
               {"indices": ",".join(p["indices"]), "include_global_state": False})

    def prompt(self, ctx):
        p = ctx.p
        keep = " and ".join(f"`{i}`" for i in p["keep"])
        return f"""
On cluster A, the repository `{p['repo']}` holds the snapshot `{p['source']}` of four indices.
Legal wants a copy of {keep} kept indefinitely; the rest can go.

  1. Without taking a new snapshot of the live indices, create the snapshot `{p['clone']}` in the
     same repository containing only {keep}, copied from `{p['source']}`.
  2. Delete `{p['source']}`.
  3. Verify that the repository is reachable from all nodes, and clean up any unreferenced data
     left in it.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _snapshot/{p['repo']}/{p['source']}/_clone/{p['clone']}
{{
  "indices": "{','.join(p['keep'])}"
}}

GET _snapshot/{p['repo']}/{p['clone']}

DELETE _snapshot/{p['repo']}/{p['source']}

POST _snapshot/{p['repo']}/_verify
POST _snapshot/{p['repo']}/_cleanup
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        snap = h.wait_for(lambda: (lambda s: s if s and s.get("state") == "SUCCESS" else None)(
            h.snapshot_info(es, p["repo"], p["clone"])), seconds=10)
        if c.check(snap, f"snapshot {p['clone']} exists and completed"):
            c.equal(sorted(snap.get("indices", [])), p["keep"], "it contains exactly the requested indices")
        status, response = h.send(es, "GET", f"/_snapshot/{p['repo']}/_all")
        names = sorted(s["snapshot"] for s in (response or {}).get("snapshots", []))
        c.check(status == 200 and p["source"] not in names, f"{p['source']} was deleted", f"snapshots: {names}")
        c.check(p["clone"] in names and len(names) == 1, f"{p['clone']} is the only snapshot left", f"snapshots: {names}")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid, snapshots=True)
