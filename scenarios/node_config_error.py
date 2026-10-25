from lib import docker, nodes
from lib.scenariolib import Scenario, check_cluster_green
from lib.tasklib import get

# (variant, how to break the config text, explanation)
VARIANTS = {
    "missing-cert": "the HTTP TLS certificate path points to a file that doesn't exist",
    "misspelled-setting": "a TLS setting name is misspelled, and Elasticsearch refuses unknown settings",
    "broken-yaml": "the YAML is invalid: a setting is indented under another one by mistake",
    "cluster-name": "cluster.name was changed, so the node starts but can't join its cluster",
}


def broken(text, node, variant):
    if variant == "missing-cert":
        return text.replace(f"xpack.security.http.ssl.certificate: certs/{node}/{node}.crt",
                            f"xpack.security.http.ssl.certificate: certs/{node}/{node}-new.crt")
    if variant == "misspelled-setting":
        return text.replace("xpack.security.transport.ssl.verification_mode:",
                            "xpack.security.transport.ssl.verfication_mode:")
    if variant == "broken-yaml":
        return text.replace("node.attr.temp:", "  node.attr.temp:", 1)
    return text.replace(f"cluster.name: cluster-{node[3]}", f"cluster.name: cluster-{node[3]}-new")


class NodeConfigError(Scenario):
    id = "node-config-error"
    title = "A node doesn't come back after a config change"
    covers = ["security.production.troubleshoot-tls", "cluster.maintenance.node-settings",
              "cluster.health.fix-red-yellow", "cluster.health.cat-apis"]
    requires = ("shell",)

    def params(self, rnd, iid):
        return {"node": rnd.choice(["es-a2", "es-a3"]), "variant": rnd.choice(sorted(VARIANTS))}

    def cause(self, ctx):
        p = ctx.p
        nodes.write(p["node"], broken(nodes.read(p["node"]), p["node"], p["variant"]))
        docker.compose("restart", p["node"], capture=True)

    def brief(self, ctx):
        n = ctx.p["node"][3:]
        return f"""
After someone edited the configuration of node {ctx.p['node']} and restarted it, cluster A runs
with only two nodes.

Fix it so that all three nodes are back in cluster A and it is green, with security and TLS
still enabled on every node. Useful: `docker compose logs --tail 50 {ctx.p['node']}` (the node's
log), `./ece config {n}` (edit its elasticsearch.yml, works while it's stopped), `./ece restart {n}`.
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        joined = nodes.wait_joined("a", seconds=20)
        names = [n["name"] for n in es.send("GET", "/_cat/nodes?format=json&h=name")[1] or []]
        c.check(joined and p["node"] in names, f"{p['node']} is back in cluster A", f"nodes: {sorted(names)}")
        if p["node"] in names:
            info = es.get(f"/_nodes/{p['node']}/settings").get("nodes", {})
            security = get(next(iter(info.values()), {}), "settings.xpack.security", {})
            c.check(str(get(security, "http.ssl.enabled")).lower() == "true" and
                    str(get(security, "transport.ssl.enabled")).lower() == "true" and
                    str(security.get("enabled")).lower() == "true",
                    f"security and TLS are still enabled on {p['node']}")
        check_cluster_green(c, es)

    def explain(self, ctx):
        p = ctx.p
        return f"""
Cause: in {p['node']}'s elasticsearch.yml, {VARIANTS[p['variant']]}.

How to find it:
  GET _cat/nodes?v                          -> only two nodes
  docker compose ps                         -> {p['node']} exited, or runs but isn't in the cluster
  docker compose logs --tail 50 {p['node']} -> the error, e.g. "unknown setting", a missing
                                               certificate file, a YAML parse error, or "master
                                               not discovered" with a cluster name mismatch

On a real server the log is in the logs/ directory or the system journal (journalctl -u
elasticsearch). Fix the line (`./ece config {p['node'][3:]}`) and start the node again.
"""

    def fix(self, ctx):
        n = ctx.p["node"][3:]
        return f"""
# ./ece config {n}: correct the broken line (compare with the other nodes' configs), then:
# ./ece restart {n}
GET _cat/nodes?v
"""

    def apply_fix(self, ctx):
        nodes.restore(ctx.p["node"])
        return None

    def reset(self, ctx):
        nodes.restore(ctx.p["node"])
