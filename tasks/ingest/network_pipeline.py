import random

from lib.tasklib import Task
from tasks.ingest._common import check_against_reference, render_pipeline

PUBLIC = ["8.8.8.8", "1.1.1.1", "81.2.69.142", "89.160.20.128", "175.16.199.1", "216.160.83.56",
          "2.125.160.216", "67.43.156.1", "149.101.100.1", "202.196.224.1"]


def private(rnd):
    return rnd.choice([f"10.{rnd.randint(0, 255)}.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}",
                       f"192.168.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}"])


def flow(rnd):
    src = rnd.choice(PUBLIC) if rnd.random() < 0.6 else private(rnd)
    dst = rnd.choice(PUBLIC) if rnd.random() < 0.5 else private(rnd)
    return {"source": {"ip": src, "port": rnd.randint(1024, 65535)},
            "destination": {"ip": dst, "port": rnd.choice([22, 53, 80, 443, 5432])},
            "network": {"transport": rnd.choice(["tcp", "udp"])}}


class NetworkPipeline(Task):
    id = "ingest-network-pipeline"
    title = "Enrich network flows with GeoIP data, direction and community ID"
    covers = ["ingest.pipelines.processor.geoip", "ingest.pipelines.processor.network_direction",
              "ingest.pipelines.processor.community_id", "ingest.pipelines.on-failure"]

    def params(self, rnd, iid):
        props = rnd.choice([["country_iso_code", "city_name", "location"],
                            ["continent_name", "country_name", "location"],
                            ["country_iso_code", "region_name", "location"]])
        return {"pipeline": f"netflow-{iid}", "props": props}

    def processors(self, p):
        return [
            {"geoip": {"field": "source.ip", "target_field": "source.geo", "properties": p["props"],
                       "ignore_missing": True}},
            {"geoip": {"field": "destination.ip", "target_field": "destination.as",
                       "database_file": "GeoLite2-ASN.mmdb", "properties": ["asn", "organization_name"],
                       "ignore_missing": True}},
            {"network_direction": {"internal_networks": ["private"]}},
            {"community_id": {}},
        ]

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Network flow documents look like this:

  {{ "source": {{ "ip": "81.2.69.142", "port": 51234 }},
    "destination": {{ "ip": "10.0.4.12", "port": 443 }},
    "network": {{ "transport": "tcp" }} }}

Create an ingest pipeline `{p['pipeline']}` that adds:

  source.geo           only the GeoIP properties {", ".join(p['props'])} of source.ip
                       (from the default city database)
  destination.as       the autonomous system number and organization name of destination.ip
                       (properties asn and organization_name, from the ASN database)
  network.direction    inbound / outbound / internal / external, where the internal networks are
                       the private address ranges
  network.community_id the Community ID flow hash of the flow

Private addresses have no GeoIP data: those documents must still be indexed without errors.
"""

    def solution(self, ctx):
        return render_pipeline(ctx.p["pipeline"], self.processors(ctx.p))

    def verify(self, ctx, c):
        p = ctx.p
        rnd = random.Random()
        docs = [flow(rnd) for _ in range(10)]
        docs[0]["source"]["ip"], docs[0]["destination"]["ip"] = private(rnd), rnd.choice(PUBLIC)
        docs[1]["source"]["ip"], docs[1]["destination"]["ip"] = rnd.choice(PUBLIC), private(rnd)
        checks = [("source.geo holds exactly the requested properties", "source.geo"),
                  ("destination.as holds the AS number and organization", "destination.as"),
                  ("network.direction is set", "network.direction"),
                  ("network.community_id is set", "network.community_id")]
        check_against_reference(c, ctx.es, p["pipeline"], self.processors(p), docs, checks)
