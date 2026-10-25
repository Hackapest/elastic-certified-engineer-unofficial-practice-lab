import json

from lib import nodes
from lib.tasklib import Task, get
from tasks.security._helpers import curl_in_node, node_sh

INCLUDE = "xpack.security.audit.logfile.events.include"


class AuditLogging(Task):
    id = "security-audit-logging"
    title = "Enable audit logging on a node and choose which events are logged"
    covers = ["security.production.audit-logging", "cluster.maintenance.node-settings"]
    answer = "state"
    requires = ("shell",)

    def params(self, rnd, iid):
        events = rnd.choice([["authentication_failed", "access_denied"],
                             ["authentication_failed", "access_denied", "security_config_change"]])
        return {"node": rnd.choice(["es-a2", "es-a3"]), "events": events}

    def prompt(self, ctx):
        p = ctx.p
        n = p["node"][3:]
        return f"""
Security wants an audit trail. As a first step, on node `{p['node']}` of cluster A only:

  1. Enable audit logging (a static setting: `./ece config {n}`, then `./ece restart {n}`).
  2. For the whole cluster, log only these event types: {', '.join(p['events'])}.
     (This one is dynamic: no restart needed.)

Then make a request with a wrong password against that node and find the event in its audit
log file (`./ece shell {n}`, then look in the logs/ directory).
"""

    def solution(self, ctx):
        p = ctx.p
        n = p["node"][3:]
        return f"""
# ./ece config {n}   and add:
xpack.security.audit.enabled: true
# then: ./ece restart {n}

PUT _cluster/settings
{{
  "persistent": {{
    "{INCLUDE}": {json.dumps(p['events'])}
  }}
}}

# ./ece shell {n}
# curl -k -u elastic:wrong https://localhost:9200
# tail -n 5 logs/cluster-a_audit.json
"""

    def apply_solution(self, ctx):
        p = ctx.p
        nodes.set_settings(p["node"], {"xpack.security.audit.enabled": "true"})
        if not nodes.restart(p["node"]):
            return "the node didn't rejoin"
        ctx.es.put("/_cluster/settings", {"persistent": {INCLUDE: p["events"]}})
        return None

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        info = es.get(f"/_nodes/{p['node']}/settings").get("nodes", {})
        enabled = get(next(iter(info.values()), {}), "settings.xpack.security.audit.enabled")
        c.equal(str(enabled).lower(), "true", f"audit logging is enabled on {p['node']}")
        flat = get(es.get("/_cluster/settings?flat_settings=true"), "persistent", {})
        include = flat.get(INCLUDE)
        include = include if isinstance(include, list) else \
            [v for k, v in sorted(flat.items()) if k.startswith(INCLUDE + ".")]
        c.equal(sorted(include), sorted(p["events"]), "only the requested event types are logged")
        if str(enabled).lower() != "true":
            return
        curl_in_node(p["node"], "/", "elastic", "wrong-password-for-audit")
        found = False
        for _ in range(10):
            code, out = node_sh(p["node"], "grep -h authentication_failed logs/*_audit.json | tail -n 1")
            if out.strip():
                found = True
                break
            node_sh(p["node"], "sleep 1")
        c.check(found, f"a failed login shows up in {p['node']}'s audit log")

    def cleanup(self, ctx):
        ctx.es.put("/_cluster/settings", {"persistent": {INCLUDE: None}})
        nodes.restore(ctx.p["node"])
        node_sh(ctx.p["node"], "rm -f logs/*_audit.json")
