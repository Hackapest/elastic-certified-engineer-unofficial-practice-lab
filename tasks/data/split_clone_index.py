from lib.tasklib import Task, get, index_settings

SHAPES = [(1, 2), (1, 3), (2, 4), (2, 6), (3, 6)]   # (source shards, split target shards)


class SplitCloneIndex(Task):
    id = "data-split-clone-index"
    title = "Clone an index as a backup and split it into more primary shards"
    covers = ["data.index.split-shrink-clone", "data.index.blocks"]
    answer = "state"

    def params(self, rnd, iid):
        source, target = rnd.choice(SHAPES)
        return {"index": f"telemetry-{iid}", "backup": f"telemetry-{iid}-backup", "split": f"telemetry-{iid}-split",
                "source_shards": source, "target_shards": target, "docs": rnd.randint(200, 700)}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"settings": {"number_of_shards": p["source_shards"], "number_of_replicas": 0}})
        bulk = "".join(f'{{"index":{{}}}}\n{{"sensor":"s{i % 13}","value":{(i * 7) % 101}}}\n'
                       for i in range(p["docs"]))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` ({p['source_shards']} primary shard(s), no replicas) is growing faster than expected.

  1. Make an exact copy of it, `{p['backup']}`, with the same number of primary shards, without
     reindexing the documents.
  2. Split it into a new index `{p['split']}` with {p['target_shards']} primary shards and 0 replicas.
  3. All three indices must accept writes again when you're done, and the two new ones must hold
     all {p['docs']} documents.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}/_settings
{{
  "index.blocks.write": true
}}

POST {p['index']}/_clone/{p['backup']}
{{
  "settings": {{ "index.blocks.write": null }}
}}

POST {p['index']}/_split/{p['split']}
{{
  "settings": {{
    "index.number_of_shards": {p['target_shards']},
    "index.number_of_replicas": 0,
    "index.blocks.write": null
  }}
}}

PUT {p['index']}/_settings
{{
  "index.blocks.write": null
}}

GET _cluster/health/{p['backup']},{p['split']}?wait_for_status=green&timeout=60s
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        for name, shards in ((p["backup"], p["source_shards"]), (p["split"], p["target_shards"])):
            s = index_settings(es, name)
            if not c.check(s is not None, f"index {name} exists"):
                continue
            c.equal(s.get("index.number_of_shards"), str(shards), f"{name} has {shards} primary shard(s)")
            if name == p["split"]:
                c.equal(s.get("index.number_of_replicas"), "0", f"{name} has no replicas")
            # resized indices recover their primaries from the source's local shards, reindexed ones don't
            rec = es.send("GET", f"/{name}/_recovery")[1] or {}
            types = {sh.get("type") for sh in get(rec, f"{name}.shards", [])}
            c.check("LOCAL_SHARDS" in types, f"{name} was created from {p['index']} with the clone/split API",
                    f"its shards were recovered with {sorted(t for t in types if t) or 'nothing'}, not from local shards")
            es.send("GET", f"/_cluster/health/{name}?wait_for_status=green&timeout=30s")
            count = es.send("GET", f"/{name}/_count")[1] or {}
            c.equal(count.get("count"), p["docs"], f"{name} has all documents")
        for name in (p["index"], p["backup"], p["split"]):
            s = index_settings(es, name) or {}
            blocked = [k for k in ("index.blocks.write", "index.blocks.read_only") if s.get(k) == "true"]
            c.check(not blocked, f"{name} accepts writes", f"{', '.join(blocked)} is set")
