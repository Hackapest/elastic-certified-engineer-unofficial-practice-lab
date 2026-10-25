from lib.tasklib import Task, field_mapping, get
from tasks.ingest._common import send


class MappingMetadata(Task):
    id = "ingest-mapping-metadata"
    title = "Metadata fields and tuning parameters: _routing, _source, _meta, store, norms, index_options"
    covers = ["ingest.mapping.meta.routing", "ingest.mapping.meta.source", "ingest.mapping.meta.meta",
              "ingest.mapping.param.store", "ingest.mapping.param.norms", "ingest.mapping.param.index-options",
              "ingest.mapping.param.eager-global-ordinals", "ingest.mapping.param.fields"]

    def params(self, rnd, iid):
        return {"index": f"articles-{iid}", "team": rnd.choice(["content", "editorial", "search"]),
                "version": rnd.randint(2, 9), "hidden": rnd.choice(["internal", "audit"]),
                "options": rnd.choice([("docs", "only which documents contain each term"),
                                       ("freqs", "which documents contain each term and how often")])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create an index `{p['index']}` for articles, with these requirements:

  - every indexing, get or delete request must supply a custom routing value; requests without
    one must be rejected
  - the whole `{p['hidden']}` object (any field below {p['hidden']}.) is indexed and searchable but
    is not kept in the stored _source
  - the mapping carries the metadata {{ "owner": "{p['team']}", "schema_version": {p['version']} }}
  - title: full text, also stored as a separate stored field so it can be retrieved with
    stored_fields without loading _source, with a keyword sub-field `title.keyword`
  - body: full text whose scoring ignores the field length, and for which the index keeps
    {p['options'][1]} (no positions)
  - tags: keyword, aggregated very often: build its global ordinals when the index is refreshed,
    not on the first aggregation
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "_routing": {{ "required": true }},
    "_source": {{ "excludes": ["{p['hidden']}.*"] }},
    "_meta": {{ "owner": "{p['team']}", "schema_version": {p['version']} }},
    "properties": {{
      "title": {{
        "type": "text",
        "store": true,
        "fields": {{ "keyword": {{ "type": "keyword" }} }}
      }},
      "body": {{ "type": "text", "norms": false, "index_options": "{p['options'][0]}" }},
      "tags": {{ "type": "keyword", "eager_global_ordinals": true }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = send(es, "GET", f"/{p['index']}/_mapping")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return
        m = response[p["index"]]["mappings"]
        c.equal(get(m, "_routing.required"), True, "routing is required")
        excludes = get(m, "_source.excludes", [])
        c.check(any(e in (f"{p['hidden']}.*", f"{p['hidden']}*", p["hidden"]) for e in excludes)
                and get(m, "_source.enabled", True), f"{p['hidden']} is excluded from _source",
                f"_source is {m.get('_source')}")
        c.equal(m.get("_meta"), {"owner": p["team"], "schema_version": p["version"]}, "the mapping has the _meta")
        f = lambda name: field_mapping(es, p["index"], name) or {}
        t = f("title")
        c.check(t.get("type") == "text" and t.get("store") is True, "title is text with store: true", f"found {t}")
        c.equal(f("title.keyword").get("type"), "keyword", "title.keyword is a keyword sub-field")
        b = f("body")
        c.check(b.get("type") == "text" and b.get("norms") is False and b.get("index_options") == p["options"][0],
                f"body is text without norms and with index_options {p['options'][0]}", f"found {b}")
        tg = f("tags")
        c.check(tg.get("type") == "keyword" and tg.get("eager_global_ordinals") is True,
                "tags is a keyword with eager_global_ordinals", f"found {tg}")
        # Behavior: a document without routing must be rejected
        status, _ = send(es, "PUT", f"/{p['index']}/_doc/routing-check", {"title": "x"})
        c.check(status >= 400, "indexing without routing is rejected", f"HTTP {status}")
        if status < 300:
            send(es, "DELETE", f"/{p['index']}/_doc/routing-check")
