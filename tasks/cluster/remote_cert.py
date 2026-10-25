import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get  # noqa: E402

INDEX = "kibana_sample_data_ecommerce"


class RemoteCert(Task):
    id = "cluster-remote-cert"
    title = "Connect cluster B as a remote cluster in sniff and proxy mode (certificate security)"
    covers = ["cluster.remote.cert-model", "cluster.remote.settings", "cluster.remote.remote-info",
              "cluster.health.cluster-settings"]
    answer = "state"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        seeds = ["es-b1:9300", "es-b2:9300", "es-b3:9300"]
        rnd.shuffle(seeds)
        return {
            "sniff": f"{rnd.choice(['dc_east', 'cluster_b', 'analytics'])}_{iid}",
            "proxy": f"{rnd.choice(['dc_east_proxy', 'via_lb', 'gateway'])}_{iid}",
            "seeds": sorted(seeds[:2]), "proxy_node": seeds[2],
            "sniff_skip": rnd.choice([True, False]), "sockets": rnd.choice([6, 9, 12]),
        }

    def prompt(self, ctx):
        p = ctx.p
        skip = ("Cross-cluster searches must skip it, instead of failing, when it is unreachable."
                if p["sniff_skip"] else "Cross-cluster searches must fail when it is unreachable.")
        return f"""
On cluster A, add cluster B as a remote cluster twice, using the certificate-based security
model (the clusters' transport layers trust the same CA; transport port 9300). Both must be
stored as persistent cluster settings.

  1. `{p['sniff']}`: sniff mode, with the seed nodes {' and '.join(p['seeds'])}.
     {skip}
  2. `{p['proxy']}`: proxy mode, connecting only through {p['proxy_node']}, with at most
     {p['sockets']} socket connections.

Check with the remote info API that both are connected, and that
GET {p['sniff']}:{INDEX}/_count works from cluster A.
"""

    def solution(self, ctx):
        p = ctx.p
        seeds = ", ".join(f'"{s}"' for s in p["seeds"])
        return f"""
PUT _cluster/settings
{{
  "persistent": {{
    "cluster.remote.{p['sniff']}.mode": "sniff",
    "cluster.remote.{p['sniff']}.seeds": [{seeds}],
    "cluster.remote.{p['sniff']}.skip_unavailable": {str(p['sniff_skip']).lower()},
    "cluster.remote.{p['proxy']}.mode": "proxy",
    "cluster.remote.{p['proxy']}.proxy_address": "{p['proxy_node']}",
    "cluster.remote.{p['proxy']}.proxy_socket_connections": {p['sockets']}
  }}
}}

GET _remote/info
GET {p['sniff']}:{INDEX}/_count
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        persistent, transient = h.remote_settings(es, p["sniff"])
        if c.check(persistent.get("seeds"), f"{p['sniff']} is a persistent remote cluster"):
            c.equal(sorted(persistent.get("seeds") or []), p["seeds"], f"{p['sniff']} uses the seed nodes {p['seeds']}")
            c.check(persistent.get("mode", "sniff") == "sniff", f"{p['sniff']} uses sniff mode")
        h.wait_connected(es, p["sniff"], 10)
        h.wait_connected(es, p["proxy"], 10)
        info = h.send(es, "GET", "/_remote/info")[1] or {}
        c.equal(get(info, f"{p['sniff']}.skip_unavailable"), p["sniff_skip"],
                f"{p['sniff']} has skip_unavailable {str(p['sniff_skip']).lower()}")
        c.check(get(info, f"{p['sniff']}.connected"), f"{p['sniff']} is connected")
        persistent, transient = h.remote_settings(es, p["proxy"])
        if c.check(persistent.get("proxy_address"), f"{p['proxy']} is a persistent remote cluster"):
            c.equal(persistent.get("mode"), "proxy", f"{p['proxy']} uses proxy mode")
            c.equal(persistent.get("proxy_address"), p["proxy_node"], f"{p['proxy']} connects through {p['proxy_node']}")
            c.equal(get(info, f"{p['proxy']}.max_proxy_socket_connections"), p["sockets"],
                    f"{p['proxy']} opens at most {p['sockets']} sockets")
        c.check(get(info, f"{p['proxy']}.connected"), f"{p['proxy']} is connected")
        status, response = h.send(es, "GET", f"/{p['sniff']}:{INDEX}/_count")
        want = h.count(ctx.es_b, INDEX)
        c.check(status == 200 and response.get("count") == want and want,
                f"GET {p['sniff']}:{INDEX}/_count returns cluster B's count", str(response)[:200])

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
