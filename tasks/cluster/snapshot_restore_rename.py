import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, index_settings  # noqa: E402


class SnapshotRestoreRename(Task):
    id = "cluster-snapshot-restore-rename"
    title = "Restore some indices of a snapshot under new names with changed settings"
    covers = ["cluster.snapshots.restore", "cluster.snapshots.restore-rename", "cluster.snapshots.restore-partial",
              "cluster.snapshots.monitor-delete"]
    answer = "state"

    def params(self, rnd, iid):
        kinds = ["orders", "invoices", "payments", "refunds"]
        rnd.shuffle(kinds)
        return {
            "repo": f"archive-{iid}", "location": f"a/archive-{iid}",
            "snapshot": rnd.choice(["daily-2026.10.01", "daily-2026.10.02", "daily-2026.10.03"]),
            "indices": [f"{k}-{iid}" for k in kinds[:3]], "restore": sorted(f"{k}-{iid}" for k in kinds[:2]),
            "suffix": rnd.choice(["restored", "recovered", "copy"]),
            "deleted": rnd.choice([10, 20, 30]), "refresh": rnd.choice(["5s", "30s", "1m"]),
        }

    def target(self, p, index):
        return f"{p['suffix']}-{index}"

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for i, index in enumerate(p["indices"]):
            h.bulk(es, index, h.sales_docs(f"{ctx.iid}{i}", "a", 80), h.SALES_MAPPING,
                   settings={"number_of_shards": 1, "number_of_replicas": 1})
        h.must(es, "PUT", f"/_snapshot/{p['repo']}", {"type": "fs", "settings": {"location": p["location"]}})
        h.must(es, "PUT", f"/_snapshot/{p['repo']}/{p['snapshot']}?wait_for_completion=true",
               {"indices": ",".join(p["indices"]), "include_global_state": True, "feature_states": ["none"]})
        # The accident: documents deleted from the live indices after the snapshot
        for index in p["restore"]:
            h.must(es, "POST", f"/{index}/_delete_by_query?refresh=true",
                   {"query": {"match_all": {}}, "max_docs": p["deleted"]})

    def prompt(self, ctx):
        p = ctx.p
        restore = " and ".join(f"`{i}`" for i in p["restore"])
        return f"""
On cluster A, documents were deleted by mistake from {restore} after the snapshot
`{p['snapshot']}` was taken in the repository `{p['repo']}` (find it with the snapshot APIs).
The snapshot also contains other indices and the cluster's global state.

Restore only {restore} from that snapshot, next to the live indices, without touching them:

  - each restored index gets the name "{p['suffix']}-" followed by its original name
    (e.g. `{self.target(p, p['restore'][0])}`); use a rename pattern, in one restore request
  - the restored indices have no replicas and a refresh interval of {p['refresh']}
  - nothing else from the snapshot is restored: no other index, no global state
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET _snapshot/{p['repo']}/_all

POST _snapshot/{p['repo']}/{p['snapshot']}/_restore?wait_for_completion=true
{{
  "indices": "{','.join(p['restore'])}",
  "include_global_state": false,
  "rename_pattern": "(.+)",
  "rename_replacement": "{p['suffix']}-$1",
  "index_settings": {{
    "index.number_of_replicas": 0,
    "index.refresh_interval": "{p['refresh']}"
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        for i, index in enumerate(p["indices"]):
            if index not in p["restore"]:
                continue
            target = self.target(p, index)
            settings = index_settings(es, target)
            if not c.check(settings, f"{target} exists"):
                continue
            c.equal(h.count(es, target), 80, f"{target} has all {80} documents of the snapshot")
            c.equal(settings.get("index.number_of_replicas"), "0", f"{target} has no replicas")
            c.equal(h.duration_ms(settings.get("index.refresh_interval")), h.duration_ms(p["refresh"]),
                    f"{target} refreshes every {p['refresh']}")
            c.equal(h.count(es, index), 80 - p["deleted"], f"the live index {index} was left as it was")
        status, resolved = h.send(es, "GET", f"/_resolve/index/*{ctx.iid}*")
        names = sorted(i["name"] for i in (resolved or {}).get("indices", []))
        expected = sorted(p["indices"] + [self.target(p, i) for i in p["restore"]])
        c.equal(names, expected, "no other index was restored")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid, snapshots=True)
