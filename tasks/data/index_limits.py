import json

from lib.tasklib import Task, get, index_settings, temp_copy


class IndexLimits(Task):
    id = "data-index-limits"
    title = "Auto-expanding replicas and mapping limits against mapping explosion"
    covers = ["data.index.auto-expand-replicas", "data.index.mapping-limits", "data.index.dynamic-settings"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"user-events-{iid}", "expand": rnd.choice(["0-all", "1-all", "0-1"]),
                "fields": rnd.choice([50, 80, 120]), "depth": rnd.choice([3, 4, 5]),
                "nested": rnd.choice([2, 3, 5])}

    def prompt(self, ctx):
        p = ctx.p
        expand = {"0-all": "one copy of every shard on every node of the cluster, however many nodes it has "
                           "(but still work with a single node)",
                  "1-all": "a copy of every shard on every node, and at least 1 replica even on a small cluster",
                  "0-1": "1 replica when there are enough nodes, and no replica on a single-node cluster"}
        return f"""
Create the index `{p['index']}` (1 primary shard) for user events whose fields are dynamic and
come from many client applications:

  - replicas: {expand[p['expand']]}. Let Elasticsearch adjust the number of replicas
    automatically when nodes join or leave.
  - at most {p['fields']} fields in the mapping. Documents that bring new fields beyond this limit
    must still be indexed; the extra fields are just not added to the mapping.
  - objects nested at most {p['depth']} levels deep (a field at the root is at depth 1)
  - at most {p['nested']} distinct fields of type nested in the mapping
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "settings": {{
    "number_of_shards": 1,
    "auto_expand_replicas": "{p['expand']}",
    "mapping.total_fields.limit": {p['fields']},
    "mapping.total_fields.ignore_dynamic_beyond_limit": true,
    "mapping.depth.limit": {p['depth']},
    "mapping.nested_fields.limit": {p['nested']}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        s = index_settings(es, p["index"])
        if not c.check(s is not None, f"index {p['index']} exists"):
            return
        c.equal(s.get("index.number_of_shards"), "1", "1 primary shard")
        c.equal(s.get("index.auto_expand_replicas"), p["expand"], "replicas expand automatically as requested")
        c.equal(s.get("index.mapping.total_fields.limit"), str(p["fields"]), "total fields limit")
        c.equal(s.get("index.mapping.depth.limit"), str(p["depth"]), "depth limit")
        c.equal(s.get("index.mapping.nested_fields.limit"), str(p["nested"]), "nested fields limit")
        probe = f"probe-{ctx.iid}"
        es.send("DELETE", f"/{probe}")
        error = temp_copy(es, p["index"], probe)
        if not c.check(error is None, "the index settings can be copied for a test", error):
            return
        try:
            deep = "x"
            for level in range(p["depth"] + 1):
                deep = {f"l{level}": deep}
            status, _ = es.send("POST", f"/{probe}/_doc", json.dumps({"deep": deep}).encode(), "application/json")
            c.check(status == 400, f"objects deeper than {p['depth']} levels are rejected",
                    f"a document {p['depth'] + 2} levels deep returned HTTP {status}")
            wide = {f"f{i}": i for i in range(p["fields"] + 20)}
            status, response = es.send("POST", f"/{probe}/_doc?refresh=true", json.dumps(wide).encode(),
                                       "application/json")
            c.check(status in (200, 201), f"a document with {len(wide)} new fields is still indexed",
                    f"HTTP {status}: {str(response)[:200]}")
            props = get(es.send("GET", f"/{probe}/_mapping")[1] or {}, f"{probe}.mappings.properties", {})
            c.check(0 < len(props) <= p["fields"], f"no more than {p['fields']} fields were added to the mapping",
                    f"{len(props)} fields mapped")
        finally:
            es.send("DELETE", f"/{probe}")
