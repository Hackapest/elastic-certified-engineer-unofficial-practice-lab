import time

from lib import client
from lib.scenariolib import Scenario, cluster_settings
from lib.tasklib import get, short_error

INDEX = "kibana_sample_data_flights"

# (variant, settings that break the connection, description for explain)
VARIANTS = {
    "wrong-port": ({"seeds": ["es-b1:9301"]}, "the seed uses port 9301; the transport port is 9300"),
    "wrong-host": ({"seeds": ["es-b9:9300"]}, "the seed names a host (es-b9) that doesn't exist"),
    "http-port": ({"mode": "proxy", "proxy_address": "es-b1:9200"},
                  "proxy mode points at port 9200, the HTTP port; remote clusters connect to the "
                  "transport port 9300"),
}


class RemoteCluster(Scenario):
    id = "remote-cluster-unreachable"
    title = "Cross-cluster search fails: the remote cluster isn't connected"
    covers = [
        "cluster.remote.troubleshoot", "cluster.remote.settings", "cluster.remote.remote-info",
        "cluster.remote.cert-model", "search.ccs.search",
    ]
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        return {"variant": rnd.choice(sorted(VARIANTS)), "alias": f"cluster_b_{iid}"}

    def prefix(self, ctx):
        return f"cluster.remote.{ctx.p['alias']}"

    def cause(self, ctx):
        settings, _ = VARIANTS[ctx.p["variant"]]
        cluster_settings(ctx.es, {f"{self.prefix(ctx)}.{k}": v for k, v in settings.items()})

    def brief(self, ctx):
        a = ctx.p["alias"]
        return f"""
Cluster A has cluster B configured as the remote cluster `{a}`, but cross-cluster
search fails. Try it:

GET {a}:{INDEX}/_count

Fix it so that this search works from cluster A.
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/{p['alias']}:{INDEX}/_count")
        for _ in range(10):   # the first request can race the connection being opened
            if status == 200:
                break
            time.sleep(1)
            status, response = es.send("GET", f"/{p['alias']}:{INDEX}/_count")
        info = es.send("GET", "/_remote/info")[1] or {}
        c.check(get(info, f"{p['alias']}.connected"), f"cluster A is connected to {p['alias']}")
        want = client.es("b").get(f"/{INDEX}/_count")["count"]
        c.check(status == 200 and response.get("count") == want,
                f"GET {p['alias']}:{INDEX}/_count returns cluster B's count",
                short_error(response) if status != 200 else f"expected {want}, got {response.get('count')}")

    def explain(self, ctx):
        _, description = VARIANTS[ctx.p["variant"]]
        a = ctx.p["alias"]
        return f"""
Cause: the remote cluster settings for `{a}` are wrong: {description}.

How to find it:
  GET _remote/info                        -> connected: false, and the configured seeds or
                                             proxy_address and mode
  GET _cluster/settings                   -> cluster.remote.{a}.*
  The error of the search says it can't connect to the remote cluster.

Fix: point it at cluster B's transport port. In the default sniff mode that's a seed node
(es-b1:9300); in proxy mode the proxy_address. Settings that don't belong to the mode in
use must be removed (set to null) in the same request.
"""

    def fix(self, ctx):
        a = ctx.p["alias"]
        return f"""
PUT _cluster/settings
{{
  "persistent": {{
    "cluster.remote.{a}.mode": null,
    "cluster.remote.{a}.proxy_address": null,
    "cluster.remote.{a}.seeds": ["es-b1:9300"]
  }}
}}
"""

    def reset(self, ctx):
        prefix = self.prefix(ctx)
        cluster_settings(ctx.es, {f"{prefix}.{k}": None for k in ("seeds", "mode", "proxy_address",
                                                                   "skip_unavailable")})
        super().reset(ctx)
