import json

from lib.tasklib import Task, field_mapping, get, temp_copy


class DynamicTemplates(Task):
    id = "data-dynamic-templates"
    title = "Map new fields by type, name and path with dynamic templates"
    covers = ["data.dynamic.match-mapping-type", "data.dynamic.match-unmatch", "data.dynamic.path-match",
              "data.dynamic.dynamic-field-mapping", "ingest.types.keyword", "ingest.types.ip",
              "ingest.types.numeric", "ingest.mapping.param.ignore-above"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"telemetry-{iid}", "text_suffix": rnd.choice(["_text", "_txt", "_desc"]),
                "ip_suffix": rnd.choice(["_ip", "_addr"]), "path": rnd.choice(["labels", "tags", "meta"]),
                "ignore_above": rnd.choice([128, 256, 512]), "float_type": rnd.choice(["float", "half_float"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create the index `{p['index']}` without any fields mapped up front. Fields that appear in documents
later must be mapped automatically by these rules (the first matching rule wins):

  1. string fields whose name ends with "{p['text_suffix']}"  -> text
  2. string fields whose name ends with "{p['ip_suffix']}"   -> ip
  3. string fields inside the object "{p['path']}", at any depth -> keyword, ignoring values longer than {p['ignore_above']}
  4. all other string fields                       -> keyword only (no text field, no sub-fields)
  5. numbers with decimals                          -> {p['float_type']}
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "dynamic_templates": [
      {{
        "texts": {{
          "match_mapping_type": "string",
          "match": "*{p['text_suffix']}",
          "mapping": {{ "type": "text" }}
        }}
      }},
      {{
        "ips": {{
          "match_mapping_type": "string",
          "match": "*{p['ip_suffix']}",
          "mapping": {{ "type": "ip" }}
        }}
      }},
      {{
        "{p['path']}": {{
          "match_mapping_type": "string",
          "path_match": "{p['path']}.*",
          "mapping": {{ "type": "keyword", "ignore_above": {p['ignore_above']} }}
        }}
      }},
      {{
        "strings": {{
          "match_mapping_type": "string",
          "mapping": {{ "type": "keyword" }}
        }}
      }},
      {{
        "decimals": {{
          "match_mapping_type": "double",
          "mapping": {{ "type": "{p['float_type']}" }}
        }}
      }}
    ]
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/{p['index']}/_mapping")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return
        test = f"verify-{ctx.iid}"
        es.send("DELETE", f"/{test}")
        error = temp_copy(es, p["index"], test)
        if not c.check(error is None, "the index can be tested", error):
            return
        doc = {
            f"summary{p['text_suffix']}": "A long description",
            f"client{p['ip_suffix']}": "10.1.2.3",
            p["path"]: {"team": "core", "deep": {"owner": "ops"}, "count": "42"},
            "status": "ok",
            "latency": 12.5,
            "retries": 3,
        }
        try:
            status, response = es.send("POST", f"/{test}/_doc?refresh=true", json.dumps(doc).encode(),
                                       "application/json")
            if not c.check(status in (200, 201), "a test document can be indexed", str(response)[:200]):
                return
            def field(name):
                return field_mapping(es, test, name) or {}
            c.equal(field(f"summary{p['text_suffix']}").get("type"), "text", f"*{p['text_suffix']} strings become text")
            c.equal(field(f"client{p['ip_suffix']}").get("type"), "ip", f"*{p['ip_suffix']} strings become ip")
            for name in (f"{p['path']}.team", f"{p['path']}.deep.owner", f"{p['path']}.count"):
                f = field(name)
                c.equal((f.get("type"), f.get("ignore_above")), ("keyword", p["ignore_above"]),
                        f"{name} is a keyword with ignore_above {p['ignore_above']}")
            status_field = field("status")
            c.equal((status_field.get("type"), status_field.get("fields")), ("keyword", None),
                    "other strings become keyword only")
            c.equal(field("latency").get("type"), p["float_type"], f"decimals become {p['float_type']}")
            c.equal(field("retries").get("type"), "long", "whole numbers stay long")
        finally:
            es.send("DELETE", f"/{test}")
        props = get(es.get(f"/{p['index']}/_mapping"), f"{p['index']}.mappings.properties", {})
        c.check(not props, "no fields are mapped up front", f"mapped: {', '.join(props)}")
