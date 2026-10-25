import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get  # noqa: E402


class SnapshotSlm(Task):
    id = "cluster-snapshot-slm"
    title = "Nightly snapshots with an SLM policy, schedule and retention"
    covers = ["cluster.snapshots.slm", "cluster.snapshots.fs-repository", "cluster.snapshots.monitor-delete"]
    answer = "state"

    def params(self, rnd, iid):
        return {
            "repo": f"nightly-repo-{iid}", "location": f"a/nightly-{iid}", "policy": f"nightly-{iid}",
            "prefix": f"crm-{iid}", "indices": [f"crm-{iid}-contacts", f"crm-{iid}-deals"],
            "other": f"audit-{iid}",
            "hour": rnd.choice([0, 1, 2, 3, 23]), "minute": rnd.choice([0, 15, 30, 45]),
            "expire": rnd.choice([7, 14, 30]), "min": rnd.choice([3, 5]), "max": rnd.choice([20, 50]),
        }

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for i, index in enumerate(p["indices"] + [p["other"]]):
            h.bulk(es, index, h.sales_docs(f"{ctx.iid}{i}", "a", 30), h.SALES_MAPPING)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
On cluster A, set up nightly backups of the CRM indices (`{p['prefix']}-*`):

  1. Register the shared file system repository `{p['repo']}` at the location "{p['location']}"
     (relative to path.repo).
  2. Create the snapshot lifecycle policy `{p['policy']}`:
       - runs every day at {p['hour']:02d}:{p['minute']:02d} (UTC)
       - snapshot names look like `<nightly-{ctx.iid}-{{now/d}}>` (use exactly this name expression)
       - snapshots go to `{p['repo']}` and contain all indices matching `{p['prefix']}-*` and
         nothing else, without the global state
       - snapshots expire after {p['expire']} days, but at least {p['min']} and at most {p['max']}
         snapshots are kept
  3. Don't wait for tonight: run the policy once now, and check that its snapshot succeeded.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _snapshot/{p['repo']}
{{
  "type": "fs",
  "settings": {{ "location": "{p['location']}" }}
}}

PUT _slm/policy/{p['policy']}
{{
  "schedule": "0 {p['minute']} {p['hour']} * * ?",
  "name": "<nightly-{ctx.iid}-{{now/d}}>",
  "repository": "{p['repo']}",
  "config": {{
    "indices": ["{p['prefix']}-*"],
    "include_global_state": false
  }},
  "retention": {{
    "expire_after": "{p['expire']}d",
    "min_count": {p['min']},
    "max_count": {p['max']}
  }}
}}

POST _slm/policy/{p['policy']}/_execute

GET _slm/policy/{p['policy']}
GET _snapshot/{p['repo']}/_all
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        repo = h.repository(es, p["repo"])
        if c.check(repo, f"repository {p['repo']} exists"):
            c.check(repo.get("type") == "fs" and h.location_matches(repo, p["location"]),
                    f"it is an fs repository at {p['location']}", str(repo)[:200])
        status, response = h.send(es, "GET", f"/_slm/policy/{p['policy']}")
        if not c.check(status == 200, f"SLM policy {p['policy']} exists"):
            return
        policy = get(response, f"{p['policy']}.policy", {})
        c.equal(h.cron_fields(policy.get("schedule")), h.cron_fields(f"0 {p['minute']} {p['hour']} * * ?"),
                f"it runs daily at {p['hour']:02d}:{p['minute']:02d}")
        c.equal(policy.get("name"), f"<nightly-{ctx.iid}-{{now/d}}>", "snapshot names use the date math expression")
        c.equal(policy.get("repository"), p["repo"], f"snapshots go to {p['repo']}")
        indices = get(policy, "config.indices")
        indices = [indices] if isinstance(indices, str) else indices
        resolved = set()
        for pattern in indices or []:
            for part in pattern.split(","):
                st, r = h.send(es, "GET", f"/_resolve/index/{part.strip()}")
                if st == 200:
                    resolved |= {i["name"] for i in r.get("indices", [])}
        c.equal(sorted(resolved), sorted(p["indices"]), "the policy snapshots exactly the CRM indices")
        c.check(get(policy, "config.include_global_state") is False, "the global state is not included")
        retention = policy.get("retention", {})
        c.equal(h.duration_ms(retention.get("expire_after")), h.duration_ms(f"{p['expire']}d"),
                f"snapshots expire after {p['expire']} days")
        c.equal((retention.get("min_count"), retention.get("max_count")), (p["min"], p["max"]),
                f"retention keeps {p['min']} to {p['max']} snapshots")

        def taken():
            st, r = h.send(es, "GET", f"/_snapshot/{p['repo']}/_all")
            snaps = [s for s in (r or {}).get("snapshots", []) if get(s, "metadata.policy") == p["policy"]] \
                if st == 200 else []
            return [s for s in snaps if s.get("state") == "SUCCESS"]
        done = h.wait_for(taken, seconds=20) if repo else []
        c.check(done, "the policy has taken a successful snapshot", "no successful snapshot made by the policy")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid, snapshots=True)
