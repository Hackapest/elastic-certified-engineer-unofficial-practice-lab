from lib.tasklib import Task, field_mapping
from tasks.ingest._common import send


class TypesSearchFields(Task):
    id = "ingest-types-search-fields"
    title = "Field types for search features: search_as_you_type, completion, wildcard, match_only_text, token_count, alias"
    covers = ["ingest.types.search-as-you-type", "ingest.types.completion", "ingest.types.wildcard",
              "ingest.types.match-only-text", "ingest.types.token-count", "ingest.types.alias",
              "ingest.mapping.param.fields"]

    def params(self, rnd, iid):
        return {"index": f"places-{iid}", "shingles": rnd.choice([2, 3, 4]),
                "alias": rnd.choice(["label", "title"]), "analyzer": rnd.choice(["standard", "whitespace"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create the index `{p['index']}` with this mapping:

  name          a field for as-you-type matching of partial words anywhere in the name, with
                shingle sub-fields up to {p['shingles']} words (the type built for that, not an analyzer)
  name_suggest  a field for fast prefix suggestions with the completion suggester
  raw_log       long machine-generated strings searched with leading wildcards and regexps,
                using the field type optimized for that
  description   full text that is only searched (never scored by term positions), using the
                space-saving variant of text
  summary       full text, with a sub-field `summary.words` that indexes the number of tokens
                produced by the {p['analyzer']} analyzer
  {p['alias']:<13} another name for the field `name`, usable in queries
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "properties": {{
      "name": {{ "type": "search_as_you_type", "max_shingle_size": {p['shingles']} }},
      "name_suggest": {{ "type": "completion" }},
      "raw_log": {{ "type": "wildcard" }},
      "description": {{ "type": "match_only_text" }},
      "summary": {{
        "type": "text",
        "fields": {{
          "words": {{ "type": "token_count", "analyzer": "{p['analyzer']}" }}
        }}
      }},
      "{p['alias']}": {{ "type": "alias", "path": "name" }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = send(es, "HEAD", f"/{p['index']}")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return
        f = lambda name: field_mapping(es, p["index"], name) or {}
        n = f("name")
        c.check(n.get("type") == "search_as_you_type" and n.get("max_shingle_size", 3) == p["shingles"],
                f"name is search_as_you_type with max_shingle_size {p['shingles']}", f"found {n}")
        c.equal(f("name_suggest").get("type"), "completion", "name_suggest is a completion field")
        c.equal(f("raw_log").get("type"), "wildcard", "raw_log is a wildcard field")
        c.equal(f("description").get("type"), "match_only_text", "description is match_only_text")
        c.equal(f("summary").get("type"), "text", "summary is text")
        w = f("summary.words")
        c.check(w.get("type") == "token_count" and w.get("analyzer") == p["analyzer"],
                f"summary.words is a token_count with the {p['analyzer']} analyzer", f"found {w}")
        a = f(p["alias"])
        c.check(a.get("type") == "alias" and a.get("path") == "name", f"{p['alias']} is an alias of name",
                f"found {a}")
