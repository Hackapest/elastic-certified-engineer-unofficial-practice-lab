import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get, index_settings  # noqa: E402


class SnapshotDrExam(Task):
    id = "cluster-snapshot-dr-exam"
    title = "Exam-style: back up cluster A with SLM and restore its data on cluster B"
    covers = ["cluster.snapshots.fs-repository", "cluster.snapshots.slm", "cluster.snapshots.create",
              "cluster.snapshots.restore-other-cluster", "cluster.snapshots.restore-rename",
              "cluster.snapshots.restore", "cluster.snapshots.restore-partial"]
    size = "exam"
    answer = "state"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        return {
            "repo": f"dr-{iid}", "location": f"shared/dr-{iid}", "policy": f"dr-hourly-{iid}",
            "prefix": f"billing-{iid}", "indices": [f"billing-{iid}-accounts", f"billing-{iid}-invoices"],
            "other": f"scratch-{iid}", "minute": rnd.choice([5, 10, 20, 40, 50]),
            "expire": rnd.choice([2, 3, 7]), "max": rnd.choice([24, 48, 72]),
            "manual": rnd.choice(["baseline", "pre-migration", "golden"]),
            "restore": f"billing-{iid}-invoices", "dr_suffix": rnd.choice(["dr", "standby", "replica"]),
            "docs": {"accounts": 40, "invoices": rnd.choice([90, 120, 150])},
            "rate": rnd.choice(["25mb", "40mb", "80mb"]),
        }

    def target(self, p):
        return f"{p['restore']}-{p['dr_suffix']}"

    def setup(self, ctx):
        p, a = ctx.p, ctx.es_a
        h.bulk(a, p["indices"][0], h.sales_docs(f"{ctx.iid}0", "a", p["docs"]["accounts"]), h.SALES_MAPPING)
        h.bulk(a, p["indices"][1], h.sales_docs(f"{ctx.iid}1", "a", p["docs"]["invoices"]), h.SALES_MAPPING)
        h.bulk(a, p["other"], h.sales_docs(f"{ctx.iid}2", "a", 10), h.SALES_MAPPING)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster B is the disaster recovery site for cluster A's billing indices (`{p['prefix']}-*`).
All nodes of both clusters mount the same snapshot volume at path.repo
(/usr/share/elasticsearch/snapshots).

On cluster A:
  1. Register the shared file system repository `{p['repo']}` at "{p['location']}" (relative to
     path.repo), with snapshots limited to {p['rate']} per second per node.
  2. Create the SLM policy `{p['policy']}` that snapshots all `{p['prefix']}-*` indices (and
     nothing else, no global state) into `{p['repo']}` every hour at minute {p['minute']}, with
     snapshot names `<billing-{{now/H}}>` (exactly this expression). Snapshots expire after
     {p['expire']} days, and at most {p['max']} are kept.
  3. Take a manual snapshot named `{p['manual']}` of the same indices, without global state,
     into `{p['repo']}`, and wait for it to complete.

On cluster B:
  4. Register the same location as the repository `{p['repo']}` in a way that cluster B can't
     write to it.
  5. From `{p['manual']}`, restore only `{p['restore']}` as `{self.target(p)}`, with no replicas
     and with writes blocked (index.blocks.write).
"""

    def solution(self, ctx):
        p = ctx.p
        text = f"""
# On cluster A
PUT _snapshot/{p['repo']}
{{
  "type": "fs",
  "settings": {{
    "location": "{p['location']}",
    "max_snapshot_bytes_per_sec": "{p['rate']}"
  }}
}}

PUT _slm/policy/{p['policy']}
{{
  "schedule": "0 {p['minute']} * * * ?",
  "name": "<billing-{{now/H}}>",
  "repository": "{p['repo']}",
  "config": {{
    "indices": ["{p['prefix']}-*"],
    "include_global_state": false
  }},
  "retention": {{
    "expire_after": "{p['expire']}d",
    "max_count": {p['max']}
  }}
}}

PUT _snapshot/{p['repo']}/{p['manual']}?wait_for_completion=true
{{
  "indices": "{p['prefix']}-*",
  "include_global_state": false
}}

# On cluster B
PUT _snapshot/{p['repo']}
{{
  "type": "fs",
  "settings": {{
    "location": "{p['location']}",
    "readonly": true
  }}
}}

POST _snapshot/{p['repo']}/{p['manual']}/_restore?wait_for_completion=true
{{
  "indices": "{p['restore']}",
  "include_global_state": false,
  "rename_pattern": "(.+)",
  "rename_replacement": "$1-{p['dr_suffix']}",
  "index_settings": {{
    "index.number_of_replicas": 0,
    "index.blocks.write": true
  }}
}}
"""
        return text

    def apply_solution(self, ctx):
        text = self.solution(ctx)
        h.run_blocks(text)

    def verify(self, ctx, c):
        p, a, b = ctx.p, ctx.es_a, ctx.es_b
        repo = h.repository(a, p["repo"])
        if c.check(repo, f"cluster A: repository {p['repo']} exists"):
            c.check(repo.get("type") == "fs" and h.location_matches(repo, p["location"]),
                    f"cluster A: it is an fs repository at {p['location']}", str(repo)[:200])
            c.equal(get(repo, "settings.max_snapshot_bytes_per_sec"), p["rate"], f"cluster A: limited to {p['rate']}/s")
            c.check(str(get(repo, "settings.readonly", "false")).lower() == "false", "cluster A: it is writable")
        status, response = h.send(a, "GET", f"/_slm/policy/{p['policy']}")
        if c.check(status == 200, f"cluster A: SLM policy {p['policy']} exists"):
            policy = get(response, f"{p['policy']}.policy", {})
            c.equal(h.cron_fields(policy.get("schedule")), h.cron_fields(f"0 {p['minute']} * * * ?"),
                    f"the policy runs every hour at minute {p['minute']}")
            c.equal(policy.get("name"), "<billing-{now/H}>", "snapshot names use the date math expression")
            c.equal(policy.get("repository"), p["repo"], f"the policy writes to {p['repo']}")
            indices = get(policy, "config.indices")
            indices = [indices] if isinstance(indices, str) else (indices or [])
            c.check(indices and all(i.startswith(p["prefix"]) for i in indices) and any("*" in i for i in indices),
                    f"the policy snapshots the {p['prefix']}-* indices", f"found {indices}")
            c.check(get(policy, "config.include_global_state") is False, "the policy leaves out the global state")
            retention = policy.get("retention", {})
            c.equal((h.duration_ms(retention.get("expire_after")), retention.get("max_count")),
                    (h.duration_ms(f"{p['expire']}d"), p["max"]), "the policy's retention is as requested")
        snap = h.snapshot_info(a, p["repo"], p["manual"])
        if c.check(snap, f"snapshot {p['manual']} exists"):
            c.equal(snap.get("state"), "SUCCESS", "it completed successfully")
            c.equal(sorted(snap.get("indices", [])), sorted(p["indices"]), "it contains the billing indices only")
            c.equal(snap.get("include_global_state"), False, "it has no global state")
        repo_b = h.repository(b, p["repo"])
        if c.check(repo_b, f"cluster B: repository {p['repo']} exists"):
            c.check(h.location_matches(repo_b, p["location"]), f"cluster B: it points to {p['location']}")
            c.equal(str(get(repo_b, "settings.readonly")).lower(), "true", "cluster B: it is read-only")
        target = self.target(p)
        settings = index_settings(b, target)
        if c.check(settings, f"cluster B: {target} exists"):
            c.equal(h.count(b, target), p["docs"]["invoices"], f"{target} has all documents")
            c.equal(settings.get("index.number_of_replicas"), "0", f"{target} has no replicas")
            c.equal(settings.get("index.blocks.write"), "true", f"{target} blocks writes")
        status, resolved = h.send(b, "GET", f"/_resolve/index/*{ctx.iid}*")
        c.equal(sorted(i["name"] for i in (resolved or {}).get("indices", [])), [target],
                "cluster B: no other index was restored")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid, snapshots=True)
