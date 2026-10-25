from lib.tasklib import Task, field_mapping
from tasks.ingest._common import send


def as_list(v):
    return v if isinstance(v, list) else [v] if v else []


class MappingParameters(Task):
    id = "ingest-mapping-parameters"
    title = "Mapping parameters: copy_to, index, doc_values, enabled, null_value, coerce, ignore_malformed"
    covers = ["ingest.mapping.explicit", "ingest.mapping.param.copy-to", "ingest.mapping.param.index",
              "ingest.mapping.param.doc-values", "ingest.mapping.param.enabled", "ingest.mapping.param.null-value",
              "ingest.mapping.param.coerce", "ingest.mapping.param.ignore-malformed",
              "ingest.mapping.param.properties", "ingest.types.object"]

    def params(self, rnd, iid):
        return {"index": f"contacts-{iid}", "combined": rnd.choice(["full_name", "display_name"]),
                "null": rnd.choice(["unknown", "n/a", "NONE"]), "number": rnd.choice(["integer", "short", "long"]),
                "blob": rnd.choice(["raw_payload", "debug_info"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create an index `{p['index']}` with an explicit mapping for these fields:

  first_name, last_name   full text; both are also copied into `{p['combined']}`
  {p['combined']:<22}  full text, searchable (it only receives the copies)
  notes                   text that is returned in _source but can't be searched
  session_id              exact value that can be searched but never sorted or aggregated on
                          (don't keep the on-disk columnar data for it)
  {p['blob']:<22}  an object of arbitrary shape that is kept in _source but not parsed or
                          indexed at all (its sub-fields never appear in the mapping)
  status                  exact value; when a document has "status": null, it must be indexed
                          as "{p['null']}" so it can be found with a term query for "{p['null']}"
  age                     a {p['number']}; a value sent as a string (e.g. "42") must be rejected
  signup_date             a date; a malformed value must not reject the whole document
  address                 an object with city and zip, both exact values
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "properties": {{
      "first_name": {{ "type": "text", "copy_to": "{p['combined']}" }},
      "last_name": {{ "type": "text", "copy_to": "{p['combined']}" }},
      "{p['combined']}": {{ "type": "text" }},
      "notes": {{ "type": "text", "index": false }},
      "session_id": {{ "type": "keyword", "doc_values": false }},
      "{p['blob']}": {{ "type": "object", "enabled": false }},
      "status": {{ "type": "keyword", "null_value": "{p['null']}" }},
      "age": {{ "type": "{p['number']}", "coerce": false }},
      "signup_date": {{ "type": "date", "ignore_malformed": true }},
      "address": {{
        "properties": {{
          "city": {{ "type": "keyword" }},
          "zip": {{ "type": "keyword" }}
        }}
      }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = send(es, "HEAD", f"/{p['index']}")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return

        def f(name):
            return field_mapping(es, p["index"], name) or {}

        for name in ("first_name", "last_name"):
            m = f(name)
            c.check(m.get("type") == "text" and p["combined"] in as_list(m.get("copy_to")),
                    f"{name} is text and copied to {p['combined']}", f"found {m}")
        c.equal(f(p["combined"]).get("type"), "text", f"{p['combined']} is a text field")
        m = f("notes")
        c.check(m.get("type") in ("text", "match_only_text") and m.get("index") is False,
                "notes is text that isn't indexed", f"found {m}")
        m = f("session_id")
        c.check(m.get("type") == "keyword" and m.get("doc_values") is False and m.get("index", True),
                "session_id is a searchable keyword without doc_values", f"found {m}")
        m = f(p["blob"])
        c.check(m.get("enabled") is False and m.get("type", "object") == "object",
                f"{p['blob']} is an object with enabled: false", f"found {m}")
        m = f("status")
        c.check(m.get("type") == "keyword" and m.get("null_value") == p["null"],
                f"status is a keyword with null_value {p['null']}", f"found {m}")
        m = f("age")
        c.check(m.get("type") == p["number"] and m.get("coerce") is False,
                f"age is a {p['number']} with coerce disabled", f"found {m}")
        m = f("signup_date")
        c.check(m.get("type") == "date" and m.get("ignore_malformed") is True,
                "signup_date is a date with ignore_malformed", f"found {m}")
        addr = f("address")
        c.equal({k: v.get("type") for k, v in addr.get("properties", {}).items()},
                {"city": "keyword", "zip": "keyword"}, "address is an object with keyword city and zip")
