import json

from lib.tasklib import Task, field_mapping

FIRST = ["Anna", "Ben", "Chloe", "David", "Emma", "Farid", "Grace", "Hugo", "Ines", "Jonas"]
LAST = ["Meyer", "Novak", "Okafor", "Petrov", "Quinn", "Rossi", "Silva", "Tanaka"]
CITIES = ["Berlin", "Lisbon", "Oslo", "Prague", "Vienna"]


class UpdateMappingReindex(Task):
    id = "ingest-update-mapping-reindex"
    title = "Change a mapping: what works in place and what needs a reindex"
    covers = ["ingest.mapping.update-mapping", "ingest.mapping.param.fields", "ingest.reindex.reindex",
              "ingest.reindex.update-by-query-mapping", "data.aliases.swap", "ingest.types.keyword"]
    size = "exam"
    answer = "state"

    def params(self, rnd, iid):
        docs = [{"name": f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", "zip": rnd.randint(1000, 99999),
                 "city": rnd.choice(CITIES)} for _ in range(rnd.randint(40, 80))]
        return {"alias": f"customers-{iid}", "v1": f"customers-v1-{iid}", "v2": f"customers-v2-{iid}",
                "notes": rnd.choice(["notes", "comment", "remarks"]), "docs": docs}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['v1']}", {"mappings": {"properties": {
            "name": {"type": "text"}, "zip": {"type": "long"}, "city": {"type": "keyword"}}},
            "aliases": {p["alias"]: {}}})
        bulk = "".join('{"index":{}}\n' + json.dumps(d) + "\n" for d in p["docs"])
        es.send("POST", f"/{p['v1']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
An application uses the alias `{p['alias']}` (currently on the index `{p['v1']}`). It needs:

  1. `zip` as an exact-value string (keyword) instead of a number, since codes can have letters
  2. a keyword sub-field `name.raw` for exact matching and sorting on names, working for the
     documents that already exist
  3. a new text field `{p['notes']}`

All {len(p['docs'])} documents must be kept, and the application must keep working through the alias.
Some of these changes can be made to the existing index, some can't: find out which.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# zip can't change type in place, so: new index with the full mapping, reindex, move the alias.
PUT {p['v2']}
{{
  "mappings": {{
    "properties": {{
      "name": {{ "type": "text", "fields": {{ "raw": {{ "type": "keyword" }} }} }},
      "zip": {{ "type": "keyword" }},
      "city": {{ "type": "keyword" }},
      "{p['notes']}": {{ "type": "text" }}
    }}
  }}
}}

POST _reindex?refresh=true
{{
  "source": {{ "index": "{p['v1']}" }},
  "dest": {{ "index": "{p['v2']}" }}
}}

POST _aliases
{{
  "actions": [
    {{ "remove": {{ "index": "{p['v1']}", "alias": "{p['alias']}" }} }},
    {{ "add": {{ "index": "{p['v2']}", "alias": "{p['alias']}" }} }}
  ]
}}

# (Adding name.raw alone would work in place: PUT {p['v1']}/_mapping, then
#  POST {p['v1']}/_update_by_query?refresh=true to index it for the existing documents.)
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/_alias/{p['alias']}")
        indices = sorted(response) if status == 200 else []
        if not c.check(len(indices) == 1, f"{p['alias']} points to exactly one index", f"it points to {indices}"):
            return
        index = indices[0]
        c.equal((field_mapping(es, index, "zip") or {}).get("type"), "keyword", "zip is a keyword")
        c.equal((field_mapping(es, index, "name.raw") or {}).get("type"), "keyword", "name has a keyword sub-field raw")
        c.equal((field_mapping(es, index, p["notes"]) or {}).get("type"), "text", f"{p['notes']} is a text field")
        es.send("POST", f"/{p['alias']}/_refresh")
        count = es.get(f"/{p['alias']}/_count")["count"]
        c.equal(count, len(p["docs"]), "all documents are there")
        name = p["docs"][0]["name"]
        want = sum(d["name"] == name for d in p["docs"])
        got = es.post(f"/{p['alias']}/_count", {"query": {"term": {"name.raw": name}}})["count"]
        c.equal(got, want, f'existing documents are found by name.raw (e.g. "{name}")')
        zip_code = str(p["docs"][0]["zip"])
        got = es.post(f"/{p['alias']}/_count", {"query": {"term": {"zip": zip_code}}})["count"]
        c.check(got >= 1, f'existing documents are found by zip as a string (e.g. "{zip_code}")')
