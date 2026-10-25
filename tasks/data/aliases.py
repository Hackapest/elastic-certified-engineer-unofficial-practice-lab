from lib.sampledata import CONTINENTS, ECOMMERCE
from lib.tasklib import Task


class Aliases(Task):
    id = "data-aliases"
    title = "Swap an alias, add a filtered alias and a write alias"
    covers = ["data.aliases.swap", "data.aliases.add-remove", "data.aliases.filtered", "data.aliases.write-index"]
    answer = "state"

    def params(self, rnd, iid):
        return {"v1": f"orders-v1-{iid}", "v2": f"orders-v2-{iid}", "read": f"orders-{iid}",
                "filtered": f"orders-{rnd.choice(['eu', 'local', 'region'])}-{iid}", "write": f"orders-write-{iid}",
                "continent": rnd.choice(CONTINENTS)}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for index, size in ((p["v1"], 1000), (p["v2"], 2000)):
            es.post("/_reindex?refresh=true", {"source": {"index": ECOMMERCE, "size": size}, "max_docs": size,
                                               "dest": {"index": index}}, timeout=120)
        es.post("/_aliases", {"actions": [{"add": {"index": p["v1"], "alias": p["read"]}}]})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Applications read orders through the alias `{p['read']}`, which points to `{p['v1']}`. The data has
been reindexed into `{p['v2']}`.

  1. Switch `{p['read']}` to `{p['v2']}` in one atomic request, so there is no moment where the
     alias points to both indices or to none.
  2. Add the alias `{p['filtered']}` on `{p['v2']}` that only shows orders from customers in
     {p['continent']} (geoip.continent_name).
  3. Add the alias `{p['write']}` that points to both indices for reading, where documents indexed
     through the alias go to `{p['v2']}`.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST _aliases
{{
  "actions": [
    {{ "remove": {{ "index": "{p['v1']}", "alias": "{p['read']}" }} }},
    {{ "add": {{ "index": "{p['v2']}", "alias": "{p['read']}" }} }}
  ]
}}

POST _aliases
{{
  "actions": [
    {{
      "add": {{
        "index": "{p['v2']}",
        "alias": "{p['filtered']}",
        "filter": {{ "term": {{ "geoip.continent_name": "{p['continent']}" }} }}
      }}
    }},
    {{ "add": {{ "index": "{p['v1']}", "alias": "{p['write']}", "is_write_index": false }} }},
    {{ "add": {{ "index": "{p['v2']}", "alias": "{p['write']}", "is_write_index": true }} }}
  ]
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es

        def indices(alias):
            status, response = es.send("GET", f"/_alias/{alias}")
            return (response or {}) if status == 200 else {}

        c.equal(sorted(indices(p["read"])), [p["v2"]], f"{p['read']} points only to {p['v2']}")
        filtered = indices(p["filtered"])
        if c.equal(sorted(filtered), [p["v2"]], f"{p['filtered']} points to {p['v2']}"):
            got = es.get(f"/{p['filtered']}/_count")["count"]
            want = es.post(f"/{p['v2']}/_count", {"query": {"term": {"geoip.continent_name": p["continent"]}}})["count"]
            all_docs = es.get(f"/{p['v2']}/_count")["count"]
            c.check(got == want and got < all_docs, f"{p['filtered']} only shows orders from {p['continent']}",
                    f"it shows {got} orders; {want} are from {p['continent']}")
        write = indices(p["write"])
        c.equal(sorted(write), sorted([p["v1"], p["v2"]]), f"{p['write']} points to both indices")
        writers = [i for i, a in write.items() if a.get("aliases", {}).get(p["write"], {}).get("is_write_index")]
        c.equal(writers, [p["v2"]], f"writes through {p['write']} go to {p['v2']}")
