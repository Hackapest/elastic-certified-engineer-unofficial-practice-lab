from lib.tasklib import Task, index_settings


class IndexSettingsUpdate(Task):
    id = "data-index-settings-update"
    title = "Change settings of an existing index and block writes"
    covers = ["data.index.dynamic-settings", "data.index.shards-replicas", "data.index.refresh-interval",
              "data.index.max-result-window", "data.index.blocks"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"inventory-{iid}", "replicas": rnd.choice([0, 2]), "refresh": rnd.choice(["5s", "30s", "1m"]),
                "window": rnd.choice([20000, 50000]), "docs": rnd.randint(50, 200)}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"settings": {"number_of_shards": 2, "number_of_replicas": 1}})
        bulk = "".join(f'{{"index":{{}}}}\n{{"item":"item-{i}","stock":{i % 37}}}\n' for i in range(p["docs"]))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` exists and holds data. Without recreating it or losing any documents:

  - change it to {p['replicas']} replica(s)
  - refresh it every {p['refresh']} instead of every second
  - allow paging up to {p['window']} results deep with from + size
  - block all writes to it, while it stays searchable and its settings can still be changed
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}/_settings
{{
  "index": {{
    "number_of_replicas": {p['replicas']},
    "refresh_interval": "{p['refresh']}",
    "max_result_window": {p['window']},
    "blocks.write": true
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        s = index_settings(es, p["index"]) or {}
        c.equal(s.get("index.number_of_replicas"), str(p["replicas"]), "number of replicas")
        c.equal(s.get("index.refresh_interval"), p["refresh"], "refresh interval")
        c.equal(s.get("index.max_result_window"), str(p["window"]), "max_result_window")
        status, _ = es.send("POST", f"/{p['index']}/_doc?refresh=true", b'{"item": "probe"}', "application/json")
        c.check(status == 403, "writes are blocked", f"indexing a document returned HTTP {status}")
        if status < 300:
            es.send("POST", f"/{p['index']}/_delete_by_query?refresh=true", b'{"query":{"term":{"item.keyword":"probe"}}}',
                    "application/json")
        c.check(s.get("index.blocks.read_only") != "true" and s.get("index.blocks.metadata") != "true",
                "settings can still be changed (no read_only or metadata block)",
                "a read_only or metadata block also blocks settings changes")
        status, response = es.send("GET", f"/{p['index']}/_count")
        c.check(status == 200 and response.get("count") == p["docs"], "the index is searchable with all documents",
                f"HTTP {status}: {response}")
