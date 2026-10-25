from lib.tasklib import Task, get, index_settings

SHAPES = [(4, 1), (4, 2), (6, 1), (6, 2), (6, 3), (8, 2), (8, 4)]   # (source shards, target shards)


class ShrinkIndex(Task):
    id = "data-shrink-index"
    title = "Shrink an index to fewer primary shards and replace it behind an alias"
    covers = ["data.index.split-shrink-clone", "data.index.blocks",
              "architecture.allocation.builtin-attributes", "data.aliases.add-remove"]
    answer = "state"

    def params(self, rnd, iid):
        source, target = rnd.choice(SHAPES)
        return {"index": f"shipments-{iid}", "target": f"shipments-{iid}-shrunk", "source_shards": source,
                "target_shards": target, "node": rnd.choice(["es-a1", "es-a2", "es-a3"]),
                "docs": rnd.randint(300, 900)}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"settings": {"number_of_shards": p["source_shards"], "number_of_replicas": 1}})
        bulk = "".join(f'{{"index":{{}}}}\n{{"shipment":"S-{i:05d}","weight":{(i * 37) % 500},"carrier":"c{i % 7}"}}\n'
                       for i in range(p["docs"]))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` has {p['source_shards']} primary shards and 1 replica, far too many for its size.

  1. Shrink it into a new index `{p['target']}` with {p['target_shards']} primary shard(s) and 1 replica.
     Use the node `{p['node']}` to gather the shard copies needed for the shrink.
  2. The new index must be a normal index afterwards: writable, and its shards free to be allocated
     on any node (it must not inherit the preparation settings of the source). It must become green
     and hold all {p['docs']} documents.
  3. Delete `{p['index']}`, and make the new index reachable under the old name `{p['index']}`
     (applications keep using that name for reads and writes).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}/_settings
{{
  "index.number_of_replicas": 0,
  "index.routing.allocation.require._name": "{p['node']}",
  "index.blocks.write": true
}}

GET _cluster/health/{p['index']}?wait_for_events=languid&wait_for_no_relocating_shards=true&wait_for_status=green&timeout=120s

POST {p['index']}/_shrink/{p['target']}
{{
  "settings": {{
    "index.number_of_shards": {p['target_shards']},
    "index.number_of_replicas": 1,
    "index.routing.allocation.require._name": null,
    "index.blocks.write": null
  }}
}}

GET _cluster/health/{p['target']}?wait_for_status=green&timeout=120s

DELETE {p['index']}

POST _aliases
{{
  "actions": [
    {{ "add": {{ "index": "{p['target']}", "alias": "{p['index']}" }} }}
  ]
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        s = index_settings(es, p["target"])
        if not c.check(s is not None, f"index {p['target']} exists"):
            return
        c.equal(s.get("index.number_of_shards"), str(p["target_shards"]), "number of primary shards")
        c.equal(s.get("index.number_of_replicas"), "1", "number of replicas")
        c.check(s.get("index.blocks.write") in (None, "false"), "the new index accepts writes",
                "index.blocks.write is still set")
        pinned = {k: v for k, v in s.items() if k.startswith("index.routing.allocation.require.") and v}
        c.check(not pinned, "the new index is not pinned to one node", str(pinned))
        status, health = es.send("GET", f"/_cluster/health/{p['target']}?wait_for_status=green&timeout=30s")
        c.equal(get(health, "status"), "green", "the new index is green")
        count = es.send("GET", f"/{p['target']}/_count")[1] or {}
        c.equal(count.get("count"), p["docs"], "the new index has all documents")
        aliases = es.send("GET", f"/_alias/{p['index']}")[1] or {}
        c.check(list(aliases) == [p["target"]], f"{p['index']} is an alias of {p['target']} only "
                "(the original index is deleted)", f"{p['index']} resolves to {sorted(aliases) or 'nothing'}")
