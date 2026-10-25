from lib import client
from lib.tasklib import Task, get
from tasks.security._helpers import curl_in_node

SETTINGS = ["xpack.security.http.filter.enabled", "xpack.security.http.filter.allow",
            "xpack.security.http.filter.deny"]


class IpFiltering(Task):
    id = "security-ip-filtering"
    title = "Block HTTP clients by IP address with IP filtering"
    covers = ["security.production.ip-filtering", "cluster.health.cluster-settings"]
    answer = "state"
    cluster = "b"
    requires = ("shell",)

    def params(self, rnd, iid):
        return {"network": rnd.choice(["203.0.113.0/24", "198.51.100.0/24", "192.0.2.0/24"]),
                "node": rnd.choice(["es-b2", "es-b3"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
On cluster B, block access to the REST API (HTTP layer) from:

  - the network {p['network']}
  - 127.0.0.1, i.e. scripts running on the Elasticsearch nodes themselves

while every other client (Kibana B, your browser, curl from your machine) keeps working. Make it
persistent, and don't restart any node.

Careful: if you block everyone, you lock yourself out of cluster B (then only `./ece reset`
helps). Test it from inside a node: `./ece shell {p['node'][3:]}`, then
  curl --cacert config/certs/ca/ca.crt -u elastic:elastic-lab https://127.0.0.1:9200
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# Only a deny list: addresses that aren't listed stay allowed. (Allow rules are checked
# before deny rules, so adding "allow": ["_all"] would let everything through.)
PUT _cluster/settings
{{
  "persistent": {{
    "xpack.security.http.filter.enabled": true,
    "xpack.security.http.filter.deny": ["{p['network']}", "127.0.0.1"]
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        settings = get(es.get("/_cluster/settings?flat_settings=true"), "persistent", {})
        deny = []
        for key, value in settings.items():
            if key.startswith("xpack.security.http.filter.deny"):
                deny += value if isinstance(value, list) else [value]
        c.check(p["network"] in deny, f"{p['network']} is denied in the persistent settings",
                f"persistent deny rules: {deny}")
        status, _ = curl_in_node(p["node"], "/", "elastic", "elastic-lab", host="127.0.0.1")
        c.check(status == 0, "requests from 127.0.0.1 on a node are rejected",
                f"a request from inside {p['node']} to 127.0.0.1 returned HTTP {status}")
        c.check(client.es("b").reachable("/_cluster/health"), "clients from outside still get through")
        kibana = client.kibana("b").send("GET", "/api/status")[0]
        c.equal(kibana, 200, "Kibana B still works")

    def cleanup(self, ctx):
        ctx.es.put("/_cluster/settings", {"persistent": {s: None for s in SETTINGS}})
