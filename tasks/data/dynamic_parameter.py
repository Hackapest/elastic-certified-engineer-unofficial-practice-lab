import json

from lib.tasklib import Task, field_mapping, get, temp_copy

MODES = {"true": "new fields are added to the mapping", "false": "new fields are kept in _source but not indexed",
         "runtime": "new fields become runtime fields", "strict": "documents with new fields are rejected"}


class DynamicParameter(Task):
    id = "data-dynamic-parameter"
    title = "Control dynamic mapping per object (true, false, runtime, strict)"
    covers = ["data.dynamic.dynamic-parameter", "ingest.mapping.param.dynamic", "ingest.types.object",
              "ingest.mapping.explicit"]
    answer = "state"

    def params(self, rnd, iid):
        objects = ["attributes", "raw", "extra"]
        modes = ["true", "false", "runtime"]
        rnd.shuffle(modes)
        return {"index": f"catalog-{iid}", "top": rnd.choice(["strict", "false"]), "objects": dict(zip(objects, modes))}

    def prompt(self, ctx):
        p = ctx.p
        lines = "\n".join(f"  {name:<11} an object in which {MODES[mode]}" for name, mode in p["objects"].items())
        return f"""
Create the index `{p['index']}` with these fields:

  name        text
  price       float
{lines}

At the top level (outside those objects), {MODES[p['top']]}.
"""

    def solution(self, ctx):
        p = ctx.p
        as_json = lambda mode: json.dumps({"true": True, "false": False}.get(mode, mode))
        objects = ",\n".join(f'      "{name}": {{ "type": "object", "dynamic": {as_json(mode)} }}'
                              for name, mode in p["objects"].items())
        top = as_json(p["top"])
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "dynamic": {top},
    "properties": {{
      "name": {{ "type": "text" }},
      "price": {{ "type": "float" }},
{objects}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        for field, type_ in (("name", "text"), ("price", "float")):
            c.equal((field_mapping(es, p["index"], field) or {}).get("type"), type_, f"{field} is {type_}")
        test = f"verify-{ctx.iid}"
        es.send("DELETE", f"/{test}")
        error = temp_copy(es, p["index"], test)
        if not c.check(error is None, f"index {p['index']} exists and can be tested", error):
            return
        try:
            def index(doc):
                status, _ = es.send("POST", f"/{test}/_doc?refresh=true", json.dumps(doc).encode(), "application/json")
                return status in (200, 201)

            top_ok = index({"name": "x", "surprise": "new"})
            if p["top"] == "strict":
                c.check(not top_ok, "a document with a new top-level field is rejected")
            else:
                mapped = field_mapping(es, test, "surprise")
                c.check(top_ok and mapped is None, "a new top-level field is stored but not mapped",
                        "it was rejected" if not top_ok else "it was added to the mapping")
            for name, mode in p["objects"].items():
                ok = index({"name": "x", name: {"color": "red"}})
                mapped = field_mapping(es, test, f"{name}.color")
                runtime = get(es.get(f"/{test}/_mapping"), f"{test}.mappings.runtime", {})
                if mode == "true":
                    c.check(ok and mapped is not None, f"new fields in {name} are mapped")
                elif mode == "false":
                    c.check(ok and mapped is None and f"{name}.color" not in runtime,
                            f"new fields in {name} are stored but not mapped")
                else:
                    c.check(ok and f"{name}.color" in runtime, f"new fields in {name} become runtime fields")
        finally:
            es.send("DELETE", f"/{test}")
