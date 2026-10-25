import ipaddress
import json
import math
import random

from lib.tasklib import Task, field_mapping, get
from tasks.ingest._common import send

CITIES = [("Lisbon", 38.72, -9.14), ("Madrid", 40.42, -3.70), ("Paris", 48.86, 2.35), ("Berlin", 52.52, 13.40),
          ("Rome", 41.90, 12.50), ("Vienna", 48.21, 16.37), ("Porto", 41.15, -8.61), ("Lyon", 45.76, 4.84)]


def venues(seed):
    rnd = random.Random(seed)
    docs = []
    for n, (city, lat, lon) in enumerate(CITIES):
        low = rnd.randint(1, 20) * 10
        month = rnd.randint(1, 9)
        docs.append({
            "name": f"{city} Hall", "location": {"lat": lat, "lon": lon},
            "capacity": {"gte": low, "lte": low + rnd.randint(5, 40) * 10},
            "season": {"gte": f"2026-{month:02d}-01", "lte": f"2026-{month + rnd.randint(1, 3):02d}-28"},
            "office_network": f"10.{n}.{rnd.choice([0, 16, 32])}.0/{rnd.choice([20, 24])}",
            "gateway": f"192.168.{n}.{rnd.randint(1, 254)}",
            "area": {"type": "polygon", "coordinates": [[[lon - 0.1, lat - 0.1], [lon + 0.1, lat - 0.1],
                                                         [lon + 0.1, lat + 0.1], [lon - 0.1, lat + 0.1],
                                                         [lon - 0.1, lat - 0.1]]]},
        })
    return docs


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


class TypesRangeGeo(Task):
    id = "ingest-types-range-geo"
    title = "Range, IP and geo field types (integer_range, date_range, ip_range, ip, geo_point, geo_shape)"
    covers = ["ingest.types.range", "ingest.types.ip", "ingest.types.geo-point", "ingest.types.geo-shape",
              "ingest.mapping.param.format", "ingest.methods.bulk"]

    def params(self, rnd, iid):
        return {"index": f"venues-{iid}", "seed": rnd.randrange(10**6)}

    def prompt(self, ctx):
        p = ctx.p
        docs = venues(p["seed"])
        return f"""
Create the index `{p['index']}` for event venues with a mapping that fits these documents:

  name             full text
  location         a point on the map (lat/lon object), for distance queries
  capacity         a range of integers ({{"gte": 100, "lte": 400}}); "venues that can host 250
                   people" must be a simple term query on capacity
  season           a range of dates in the format yyyy-MM-dd
  office_network   a CIDR block; a term query with one IP address must find the venue
  gateway          an IP address (searchable with CIDR notation)
  area             a polygon (GeoJSON)

Then index these 8 documents with one bulk request:

{chr(10).join("  " + json.dumps(d) for d in docs)}
"""

    def solution(self, ctx):
        p = ctx.p
        lines = "\n".join(f'{{ "index": {{}} }}\n{json.dumps(d)}' for d in venues(p["seed"]))
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "properties": {{
      "name": {{ "type": "text" }},
      "location": {{ "type": "geo_point" }},
      "capacity": {{ "type": "integer_range" }},
      "season": {{ "type": "date_range", "format": "yyyy-MM-dd" }},
      "office_network": {{ "type": "ip_range" }},
      "gateway": {{ "type": "ip" }},
      "area": {{ "type": "geo_shape" }}
    }}
  }}
}}

POST {p['index']}/_bulk?refresh=true
{lines}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = send(es, "HEAD", f"/{p['index']}")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return
        f = lambda name: (field_mapping(es, p["index"], name) or {})
        want = {"location": "geo_point", "capacity": "integer_range", "season": "date_range",
                "office_network": "ip_range", "gateway": "ip", "area": "geo_shape"}
        for name, t in want.items():
            c.equal(f(name).get("type"), t, f"{name} is a {t} field")
        c.check(f("season").get("format") in ("yyyy-MM-dd", "strict_date", "date"), "season uses the format yyyy-MM-dd",
                f"found {f('season').get('format')!r}")
        docs = venues(p["seed"])
        send(es, "POST", f"/{p['index']}/_refresh")
        status, response = send(es, "GET", f"/{p['index']}/_count")
        if not c.equal(get(response, "count"), len(docs), "the 8 documents are indexed"):
            return
        rnd = random.Random()

        def count(query):
            status, response = send(es, "GET", f"/{p['index']}/_count", {"query": query})
            return get(response, "count") if status == 200 else f"error {status}"

        people = rnd.randint(10, 400)
        c.equal(count({"term": {"capacity": people}}),
                sum(1 for d in docs if d["capacity"]["gte"] <= people <= d["capacity"]["lte"]),
                f"a term query on capacity ({people}) finds the venues whose range contains it")
        day = f"2026-{rnd.randint(2, 10):02d}-15"
        c.equal(count({"term": {"season": day}}),
                sum(1 for d in docs if d["season"]["gte"] <= day <= d["season"]["lte"]),
                f"a term query on season ({day}) finds the venues open that day")
        d = rnd.choice(docs)
        ip = str(ipaddress.ip_network(d["office_network"]).network_address + 5)
        c.equal(count({"term": {"office_network": ip}}),
                sum(1 for x in docs if ipaddress.ip_address(ip) in ipaddress.ip_network(x["office_network"])),
                f"a term query on office_network ({ip}) finds the venue")
        c.equal(count({"term": {"gateway": "192.168.0.0/22"}}),
                sum(1 for x in docs if ipaddress.ip_address(x["gateway"]) in ipaddress.ip_network("192.168.0.0/22")),
                "gateway can be searched with a CIDR block")
        origin = rnd.choice(CITIES)
        c.equal(count({"geo_distance": {"distance": "650km", "location": {"lat": origin[1], "lon": origin[2]}}}),
                sum(1 for x in docs if km((origin[1], origin[2]), (x["location"]["lat"], x["location"]["lon"])) <= 650),
                "location supports distance queries")
        c.equal(count({"geo_shape": {"area": {"shape": {"type": "point", "coordinates": [origin[2], origin[1]]},
                                              "relation": "intersects"}}}), 1, "area supports shape queries")
