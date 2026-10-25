import json

from lib.tasklib import Task, field_mapping, get, temp_copy


class RuntimeDynamicTemplate(Task):
    id = "data-runtime-dynamic-template"
    title = "Map new fields as runtime fields with dynamic templates"
    covers = ["data.dynamic.runtime-dynamic-template", "data.dynamic.match-mapping-type", "data.dynamic.path-match"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"events-rt-{iid}", "object": rnd.choice(["attributes", "context", "extra"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create the index `{p['index']}` with a mapped date field `@timestamp`. Fields that show up later
inside the object `{p['object']}` must not be indexed, but still be searchable as runtime fields:

  strings  -> runtime keyword
  numbers  -> runtime double (whole numbers too)

New fields anywhere else are mapped as usual (indexed, default dynamic mapping).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "dynamic_templates": [
      {{
        "{p['object']}_strings": {{
          "path_match": "{p['object']}.*",
          "match_mapping_type": "string",
          "runtime": {{ "type": "keyword" }}
        }}
      }},
      {{
        "{p['object']}_numbers": {{
          "path_match": "{p['object']}.*",
          "match_mapping_type": ["long", "double"],
          "runtime": {{ "type": "double" }}
        }}
      }}
    ],
    "properties": {{
      "@timestamp": {{ "type": "date" }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        c.equal((field_mapping(es, p["index"], "@timestamp") or {}).get("type"), "date", "@timestamp is a date")
        test = f"verify-{ctx.iid}"
        es.send("DELETE", f"/{test}")
        error = temp_copy(es, p["index"], test)
        if not c.check(error is None, f"index {p['index']} exists and can be tested", error):
            return
        try:
            doc = {"@timestamp": "2026-10-25T10:00:00Z", p["object"]: {"user": "anna", "count": 3, "ratio": 0.5},
                   "status": "ok"}
            status, response = es.send("POST", f"/{test}/_doc?refresh=true", json.dumps(doc).encode(),
                                       "application/json")
            if not c.check(status in (200, 201), "a test document can be indexed", str(response)[:200]):
                return
            mapping = es.get(f"/{test}/_mapping")[test]["mappings"]
            runtime = mapping.get("runtime", {})
            c.equal(get(runtime, f"{p['object']}.user.type", runtime.get(f"{p['object']}.user", {}).get("type")),
                    "keyword", f"strings in {p['object']} become runtime keyword fields")
            for name in ("count", "ratio"):
                c.equal(runtime.get(f"{p['object']}.{name}", {}).get("type"), "double",
                        f"numbers in {p['object']} ({name}) become runtime double fields")
            c.check(field_mapping(es, test, f"{p['object']}.user") is None, f"fields in {p['object']} aren't indexed")
            c.check(field_mapping(es, test, "status") is not None, "other new fields are mapped as usual")
        finally:
            es.send("DELETE", f"/{test}")
