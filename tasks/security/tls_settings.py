from lib import nodes
from lib.tasklib import Task, get
from tasks.security._helpers import node_sh

PROTOCOLS = "xpack.security.http.ssl.supported_protocols"


def handshake(node, version):
    """Can a client connect to the node's HTTP port with exactly this TLS version? (curl inside the node)"""
    flag = {"1.2": "--tlsv1.2 --tls-max 1.2", "1.3": "--tlsv1.3 --tls-max 1.3"}[version]
    code, out = node_sh(node, f"curl -s -o /dev/null -w '%{{http_code}}' {flag} --cacert config/certs/ca/ca.crt "
                              f"https://localhost:9200/")
    return out.strip() not in ("", "000")


class TlsSettings(Task):
    id = "security-tls-settings"
    title = "Allow only TLS 1.3 on a node's HTTP layer"
    covers = ["security.production.tls-settings", "cluster.maintenance.node-settings"]
    answer = "state"
    requires = ("shell",)

    def params(self, rnd, iid):
        return {"node": rnd.choice(["es-a2", "es-a3"])}

    def prompt(self, ctx):
        p = ctx.p
        n = p["node"][3:]
        return f"""
A security review demands that node `{p['node']}` of cluster A accepts HTTPS connections with
TLS 1.3 only (no TLS 1.2 or older) on its HTTP layer. The transport layer between the nodes
stays as it is.

Find the right setting, put it in the node's elasticsearch.yml (`./ece config {n}`) and restart
it (`./ece restart {n}`). Check from inside the node (`./ece shell {n}`):
  curl --tlsv1.2 --tls-max 1.2 --cacert config/certs/ca/ca.crt https://localhost:9200   (must fail)
  curl --tlsv1.3 --cacert config/certs/ca/ca.crt https://localhost:9200                 (must connect)
"""

    def solution(self, ctx):
        n = ctx.p["node"][3:]
        return f"""
# ./ece config {n}   and add:
{PROTOCOLS}: [ "TLSv1.3" ]
# then: ./ece restart {n}

GET _nodes/{ctx.p['node']}/settings?filter_path=**.http.ssl.supported_protocols
"""

    def apply_solution(self, ctx):
        nodes.set_settings(ctx.p["node"], {PROTOCOLS: '[ "TLSv1.3" ]'})
        return None if nodes.restart(ctx.p["node"]) else "the node didn't rejoin"

    def verify(self, ctx, c):
        p = ctx.p
        if not c.check(nodes.running(p["node"]) and nodes.wait_joined("a", seconds=30),
                       f"{p['node']} is running and in the cluster"):
            return
        c.check(not handshake(p["node"], "1.2"), f"{p['node']} refuses TLS 1.2 connections on HTTP")
        c.check(handshake(p["node"], "1.3"), f"{p['node']} accepts TLS 1.3 connections on HTTP")
        info = ctx.es.get(f"/_nodes/{p['node']}/settings").get("nodes", {})
        transport = get(next(iter(info.values()), {}), "settings.xpack.security.transport.ssl.supported_protocols")
        c.check(transport is None, "the transport layer is unchanged", f"transport protocols: {transport}")

    def cleanup(self, ctx):
        nodes.restore(ctx.p["node"])
