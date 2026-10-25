from lib.sampledata import FLIGHTS
from lib.tasklib import Task, get
from tasks.security._helpers import Probe, api_keys, count, err, invalidate_keys, send_json


class ApiKeyCreate(Task):
    id = "security-api-key-create"
    title = "Create an API key with limited privileges, an expiration and metadata"
    covers = ["security.rbac.api-keys", "security.rbac.roles"]
    answer = "state"

    def params(self, rnd, iid):
        app = rnd.choice(["inventory-sync", "price-updater", "stock-importer", "catalog-bot"])
        return {"key": f"{app}-{iid}", "rw": f"inventory-{iid}", "ro": f"catalog-{iid}",
                "days": rnd.choice([7, 30, 90]), "team": rnd.choice(["warehouse", "retail", "supply"]),
                "descriptor": f"{app.split('-')[0]}-access"}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for index in (p["rw"], p["ro"]):
            es.put(f"/{index}/_doc/1?refresh=true", {"sku": "A-1", "qty": 3})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
An application needs credentials for cluster A. Create an API key:

  - name: `{p['key']}`
  - it expires {p['days']} days after creation
  - metadata: "team": "{p['team']}" and "environment": "production"
  - it can search and write (index, update, delete documents) in `{p['rw']}`, can only search
    `{p['ro']}`, and has no other access: no other index, no cluster privileges.
    Name the role descriptor `{p['descriptor']}`.

Without role descriptors, an API key gets all the privileges of the user who creates it.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST _security/api_key
{{
  "name": "{p['key']}",
  "expiration": "{p['days']}d",
  "role_descriptors": {{
    "{p['descriptor']}": {{
      "cluster": [],
      "indices": [
        {{ "names": ["{p['rw']}"], "privileges": ["read", "write"] }},
        {{ "names": ["{p['ro']}"], "privileges": ["read"] }}
      ]
    }}
  }},
  "metadata": {{
    "team": "{p['team']}",
    "environment": "production"
  }}
}}

# Check it:
GET _security/api_key?name={p['key']}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        keys = [k for k in api_keys(es, p["key"], active_only=True) if k["name"] == p["key"]]
        if not c.check(len(keys) == 1, f"there is one active API key named {p['key']}", f"found {len(keys)}"):
            return
        key = keys[0]
        if c.check(key.get("expiration"), "the key expires"):
            days = (key["expiration"] - key["creation"]) / 86400000
            c.check(abs(days - p["days"]) < 0.05, f"the key expires {p['days']} days after creation",
                    f"it expires {days:.2f} days after creation")
        c.equal({k: get(key, f"metadata.{k}") for k in ("team", "environment")},
                {"team": p["team"], "environment": "production"}, "the key has the metadata")
        c.check(p["descriptor"] in (key.get("role_descriptors") or {}),
                f"the key has a role descriptor named {p['descriptor']}")
        probe = Probe("a", es, ctx.iid, key.get("role_descriptors"))
        if not c.check(probe.ok, "the key's privileges can be tested", probe.error):
            return
        try:
            k = probe.client
            for index in (p["rw"], p["ro"]):
                status, n = count(k, index)
                c.check(status == 200 and n, f"the key can search {index}", f"search returned HTTP {status}")
            status, response = send_json(k, "PUT", f"/{p['rw']}/_doc/2?refresh=true", {"sku": "B-2", "qty": 1})
            c.check(status in (200, 201), f"the key can write to {p['rw']}", err(status, response))
            status, response = k.send("DELETE", f"/{p['rw']}/_doc/2")
            c.check(status == 200, f"the key can delete documents in {p['rw']}", err(status, response))
            status, _ = send_json(k, "PUT", f"/{p['ro']}/_doc/2", {"sku": "B-2", "qty": 1})
            c.check(status == 403, f"the key can't write to {p['ro']}", f"the write returned HTTP {status}")
            es.send("DELETE", f"/{p['ro']}/_doc/2")
            status, _ = count(k, FLIGHTS)
            c.check(status == 403, "the key can't read other indices", f"searching {FLIGHTS} returned HTTP {status}")
            status, _ = k.send("GET", "/_cluster/health")
            c.check(status == 403, "the key has no cluster privileges", f"cluster health returned HTTP {status}")
        finally:
            probe.close()

    def cleanup(self, ctx):
        invalidate_keys(ctx.es, ctx.iid)
