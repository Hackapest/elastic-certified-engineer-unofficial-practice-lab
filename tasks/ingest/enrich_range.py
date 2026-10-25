import ipaddress
import json
import random

from lib.tasklib import Task, get, index_settings
from tasks.ingest._common import MISSING, bulk, field, send

SITES = ["berlin-dc1", "paris-dc2", "dublin-office", "lab", "warehouse", "tokyo-dc3"]


def subnets(seed):
    rnd = random.Random(seed)
    nets = []
    for n, site in enumerate(SITES):
        prefix = rnd.choice([16, 20, 24])
        net = ipaddress.ip_network(f"10.{10 + n * 20}.{rnd.randint(0, 15) * 16}.0/{prefix}", strict=False)
        nets.append({"cidr": str(net), "site": site, "vlan": 100 + n * 10})
    return nets


def ip_in(rnd, cidr):
    net = ipaddress.ip_network(cidr)
    return str(net.network_address + rnd.randint(1, net.num_addresses - 2))


class EnrichRange(Task):
    id = "ingest-enrich-range"
    title = "Look up the subnet of an IP with a range enrich policy, applied as a default pipeline"
    covers = ["ingest.pipelines.enrich-policy", "ingest.pipelines.processor.enrich",
              "ingest.pipelines.default-final", "ingest.types.range", "ingest.types.ip"]

    def params(self, rnd, iid):
        return {"subnets": f"subnets-{iid}", "policy": f"subnet-lookup-{iid}", "pipeline": f"assets-subnet-{iid}",
                "index": f"assets-{iid}", "seed": rnd.randrange(10**6), "target": rnd.choice(["network", "subnet"])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['subnets']}", {"mappings": {"properties": {
            "cidr": {"type": "ip_range"}, "site": {"type": "keyword"}, "vlan": {"type": "integer"}}}})
        bulk(es, p["subnets"], subnets(p["seed"]))

    def examples(self, p):
        rnd = random.Random(p["seed"] + 7)
        nets = subnets(p["seed"])
        return [{"host": {"name": f"srv-{n}", "ip": ip_in(rnd, nets[n]["cidr"])}} for n in range(3)]

    def prompt(self, ctx):
        p = ctx.p
        examples = "\n".join(f"  {json.dumps(e)}" for e in self.examples(p))
        return f"""
The index `{p['subnets']}` maps subnets (field `cidr`, an ip_range) to a site and a VLAN.

  1. Create an enrich policy `{p['policy']}` that finds the subnet containing an IP address and
     provides `site` and `vlan`. Make it usable.
  2. Create an ingest pipeline `{p['pipeline']}` that adds the subnet data of `host.ip` under
     `{p['target']}` (e.g. {p['target']}.site). IPs outside every subnet are indexed unchanged.
  3. Create an index `{p['index']}` (host.name keyword, host.ip ip) that runs this pipeline for
     every document indexed into it, without the client naming the pipeline.
  4. Index these documents into `{p['index']}`:

{examples}
"""

    def solution(self, ctx):
        p = ctx.p
        docs = "\n".join(f'{{ "index": {{}} }}\n{json.dumps(e)}' for e in self.examples(p))
        return f"""
PUT _enrich/policy/{p['policy']}
{{
  "range": {{
    "indices": "{p['subnets']}",
    "match_field": "cidr",
    "enrich_fields": ["site", "vlan"]
  }}
}}

POST _enrich/policy/{p['policy']}/_execute

PUT _ingest/pipeline/{p['pipeline']}
{{
  "processors": [
    {{ "enrich": {{ "policy_name": "{p['policy']}", "field": "host.ip", "target_field": "{p['target']}" }} }}
  ]
}}

PUT {p['index']}
{{
  "settings": {{ "index.default_pipeline": "{p['pipeline']}" }},
  "mappings": {{
    "properties": {{
      "host": {{ "properties": {{ "name": {{ "type": "keyword" }}, "ip": {{ "type": "ip" }} }} }}
    }}
  }}
}}

POST {p['index']}/_bulk?refresh=true
{docs}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = send(es, "GET", f"/_enrich/policy/{p['policy']}")
        policies = get(response, "policies", []) if status == 200 else []
        if c.check(policies, f"enrich policy {p['policy']} exists"):
            conf = get(policies[0], "config.range")
            if c.check(conf is not None, "it is a range policy"):
                c.equal(conf.get("match_field"), "cidr", "it matches on cidr")
                c.equal(sorted(conf.get("enrich_fields", [])), ["site", "vlan"], "it provides site and vlan")
        status, response = send(es, "GET", f"/_resolve/index/.enrich-{p['policy']}-*?expand_wildcards=all")
        c.check(status == 200 and get(response, "indices"), "the policy has been executed",
                "no enrich index found: execute the policy")
        settings = index_settings(es, p["index"])
        if not c.check(settings is not None, f"index {p['index']} exists"):
            return
        c.check(p["pipeline"] in (settings.get("index.default_pipeline"), settings.get("index.final_pipeline")),
                f"{p['index']} runs {p['pipeline']} by default",
                f"default_pipeline is {settings.get('index.default_pipeline')!r}")
        mapping = es.get(f"/{p['index']}/_mapping")[p["index"]]["mappings"]
        c.equal(get(mapping, "properties.host.properties.ip.type"), "ip", "host.ip is an ip field")
        # Simulate indexing into the index (runs its default/final pipelines)
        nets = subnets(p["seed"])
        rnd = random.Random()
        picks = rnd.sample(nets, 4)
        docs = [{"host": {"name": f"h{n}", "ip": ip_in(rnd, net["cidr"])}} for n, net in enumerate(picks)]
        docs.append({"host": {"name": "outside", "ip": "172.16.5.5"}})
        status, response = send(es, "POST", f"/_ingest/{p['index']}/_simulate",
                                {"docs": [{"_source": d} for d in docs]})
        bad = None if status == 200 else str(response)[:300]
        for d, net, r in zip(docs, picks + [None], get(response, "docs", []) if status == 200 else []):
            src = get(r, "doc._source", {})
            target = field(src, p["target"])
            if net is None:
                if target is not MISSING:
                    bad = bad or f"for {d['host']['ip']}: expected no {p['target']}, found {target!r}"
            elif not isinstance(target, dict) or (target.get("site"), target.get("vlan")) != (net["site"], net["vlan"]):
                bad = bad or f"for {d['host']['ip']}: expected site {net['site']} and vlan {net['vlan']}, found {target!r}"
        c.check(bad is None, f"documents indexed into {p['index']} get the subnet data under {p['target']}", bad)
        status, response = send(es, "GET", f"/{p['index']}/_search", {"size": 10})
        hits = get(response, "hits.hits", []) if status == 200 else []
        c.check(len(hits) == 3 and all(isinstance(field(h["_source"], p["target"]), dict) for h in hits),
                "the three example documents are indexed and enriched",
                f"found {len(hits)} documents")
