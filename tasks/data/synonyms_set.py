from lib.tasklib import Task, analyze, field_mapping, get

# (rule, a query word, the tokens the search analyzer must produce for it)
RULES = [
    ("laptop, notebook", "laptop", ["laptop", "notebook"]),
    ("tv, television", "television", ["television", "tv"]),
    ("sneakers, trainers, running shoes", "sneakers", ["sneakers", "trainers", "running", "shoes"]),
    ("mobile phone => smartphone", "mobile phone", ["smartphone"]),
    ("couch, sofa", "couch", ["couch", "sofa"]),
    ("hoodie => sweatshirt", "hoodie", ["sweatshirt"]),
]


class SynonymsSet(Task):
    id = "data-synonyms-set"
    title = "Search-time synonyms managed with the synonyms API"
    covers = ["data.analysis.synonym-sets", "data.analysis.updateable-synonyms",
              "data.analysis.filter.synonym-graph", "data.analysis.specify-analyzer",
              "ingest.mapping.param.search-analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"shop-{iid}", "set": f"shop-synonyms-{iid}", "rules": rnd.sample(range(len(RULES)), 3)}

    def prompt(self, ctx):
        p = ctx.p
        rules = "\n".join(f"  {RULES[i][0]}" for i in p["rules"])
        return f"""
Create a synonyms set named `{p['set']}` (with the synonyms API) containing these rules:

{rules}

Then create the index `{p['index']}` with a text field `title`. Documents are indexed with the
standard analyzer, but searches on `title` must expand synonyms from that set (after
lowercasing), so that the set can be changed later without reindexing.
"""

    def solution(self, ctx):
        p = ctx.p
        rules = ",\n    ".join(f'{{ "synonyms": "{RULES[i][0]}" }}' for i in p["rules"])
        return f"""
PUT _synonyms/{p['set']}
{{
  "synonyms_set": [
    {rules}
  ]
}}

PUT {p['index']}
{{
  "settings": {{
    "analysis": {{
      "filter": {{
        "shop_synonyms": {{
          "type": "synonym_graph",
          "synonyms_set": "{p['set']}",
          "updateable": true
        }}
      }},
      "analyzer": {{
        "search_with_synonyms": {{
          "type": "custom",
          "tokenizer": "standard",
          "filter": ["lowercase", "shop_synonyms"]
        }}
      }}
    }}
  }},
  "mappings": {{
    "properties": {{
      "title": {{
        "type": "text",
        "analyzer": "standard",
        "search_analyzer": "search_with_synonyms"
      }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/_synonyms/{p['set']}")
        if c.check(status == 200, f"synonyms set {p['set']} exists"):
            got = sorted("".join(r["synonyms"].split()) for r in response.get("synonyms_set", []))
            want = sorted("".join(RULES[i][0].split()) for i in p["rules"])
            c.equal(got, want, "it contains exactly the requested rules")
        mapping = field_mapping(es, p["index"], "title")
        if not c.check(mapping is not None, f"index {p['index']} has a title field"):
            return
        c.check(mapping.get("analyzer") in (None, "standard"), "documents are indexed with the standard analyzer",
                f"analyzer is {mapping.get('analyzer')}")
        search_analyzer = mapping.get("search_analyzer")
        if not c.check(search_analyzer, "title has a search analyzer"):
            return
        settings = es.get(f"/{p['index']}/_settings")[p["index"]]["settings"]
        filters = get(settings, "index.analysis.filter", {})
        uses_set = [f for f in filters.values() if f.get("synonyms_set") == p["set"]]
        c.check(uses_set and all(str(f.get("updateable")).lower() == "true" for f in uses_set),
                "the synonym filter uses the set and is updateable (search time only)",
                "no synonym filter refers to the set" if not uses_set else "the filter is not updateable")
        problem = None
        for i in p["rules"]:
            _, word, want = RULES[i]
            got = analyze(es, p["index"], word, analyzer=search_analyzer)
            if sorted(got or []) != sorted(want):
                problem = f"for {word!r}: expected {sorted(want)}, got {got}"
                break
        c.check(problem is None, "searches expand the synonyms", problem)
