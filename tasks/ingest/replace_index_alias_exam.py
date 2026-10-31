import json

from lib.tasklib import Task, exists, field_mapping, index_settings, same_analysis

TITLES = ["Moby Dick", "Great Expectations", "Pride and Prejudice", "Dracula", "Frankenstein"]
TYPOS = {"Moby Dick": "Moby Dik", "Great Expectations": "Grate Expectations",
         "Pride and Prejudice": "Pride and Prejudise", "Dracula": "Draculla", "Frankenstein": "Frankenstien"}
LINES = ["The whale AND the sea", "It was THE best of times", "An old house on a hill", "The doctor's notes, in full",
         "A letter from O'Brien and the captain"]
TEXTS = ["The Doctor's AND the Whale", "AN old e-mail: info@example.com is NOT in the book", "THE U.S.A. and a ship"]


class ReplaceIndexAliasExam(Task):
    id = "ingest-replace-index-alias-exam"
    title = "Exam-style: rebuild an index with a new analyzer, and put an alias in its place"
    covers = ["ingest.reindex.reindex", "ingest.reindex.update-by-query", "data.analysis.tokenizer.classic",
              "data.analysis.filter.stop", "data.analysis.custom-analyzer", "data.aliases.add-remove",
              "ingest.mapping.explicit", "ingest.types.keyword", "ingest.types.numeric"]
    size = "exam"
    answer = "state"

    def params(self, rnd, iid):
        wrong = rnd.choice(TITLES)
        docs = [{"line_id": i, "chapter": rnd.randint(1, 40), "title": rnd.choice(TITLES), "speaker": f"reader{i % 7}",
                 "text": rnd.choice(LINES)} for i in range(120)]
        for d in docs[::9]:
            d["title"] = wrong
        for d in docs[::18]:
            d["title"] = TYPOS[wrong]
        return {"index": f"library-{iid}", "new": f"library-rebuilt-{iid}", "wrong": TYPOS[wrong], "right": wrong,
                "docs": docs}

    def setup(self, ctx):
        p = ctx.p
        bulk = "".join('{"index":{}}\n' + json.dumps(d) + "\n" for d in p["docs"])
        ctx.es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` was created with dynamic mapping, and it shows. Rebuild it:

  1. Reindex it into the new index `{p['new']}` with 1 primary and 0 replica shards, where
       - title and speaker are keyword fields
       - line_id and chapter are long fields
       - text is a text field
     and the index's default analyzer uses the classic tokenizer and removes english stop words
     regardless of their case ("THE" and "the" both go). It does nothing else.
  2. Delete `{p['index']}`, and make the name `{p['index']}` an alias of `{p['new']}`.
  3. Through that alias, correct the misspelled title "{p['wrong']}" to "{p['right']}".
"""

    def definition(self):
        return {"analysis": {"filter": {"english_stop": {"type": "stop", "stopwords": "_english_", "ignore_case": True}},
                             "analyzer": {"default": {"type": "custom", "tokenizer": "classic",
                                                      "filter": ["english_stop"]}}}}

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['new']}
{{
  "settings": {{
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {{
      "filter": {{
        "english_stop": {{ "type": "stop", "stopwords": "_english_", "ignore_case": true }}
      }},
      "analyzer": {{
        "default": {{ "type": "custom", "tokenizer": "classic", "filter": ["english_stop"] }}
      }}
    }}
  }},
  "mappings": {{
    "properties": {{
      "title": {{ "type": "keyword" }},
      "speaker": {{ "type": "keyword" }},
      "line_id": {{ "type": "long" }},
      "chapter": {{ "type": "long" }},
      "text": {{ "type": "text" }}
    }}
  }}
}}

POST _reindex?refresh=true
{{
  "source": {{ "index": "{p['index']}" }},
  "dest": {{ "index": "{p['new']}" }}
}}

DELETE {p['index']}

POST _aliases
{{
  "actions": [
    {{ "add": {{ "index": "{p['new']}", "alias": "{p['index']}" }} }}
  ]
}}

POST {p['index']}/_update_by_query?refresh=true
{{
  "query": {{ "term": {{ "title": "{p['wrong']}" }} }},
  "script": {{ "source": "ctx._source.title = params.title", "params": {{ "title": "{p['right']}" }} }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        s = index_settings(es, p["new"])
        if not c.check(s is not None, f"index {p['new']} exists"):
            return
        c.equal((s.get("index.number_of_shards"), s.get("index.number_of_replicas")), ("1", "0"), "1 primary, 0 replicas")
        types = {f: (field_mapping(es, p["new"], f) or {}).get("type") for f in ("title", "speaker", "line_id", "chapter", "text")}
        c.equal(types, {"title": "keyword", "speaker": "keyword", "line_id": "long", "chapter": "long", "text": "text"},
                "the field types")
        reference = f"ref-{ctx.iid}"
        es.send("DELETE", f"/{reference}")
        es.put(f"/{reference}", {"settings": self.definition(), "mappings": {"properties": {"text": {"type": "text"}}}})
        try:
            same_analysis(c, es, p["new"], reference, TEXTS, "the default analyzer: classic tokenizer, stop words in any case",
                          field="text")
        finally:
            es.send("DELETE", f"/{reference}")
        status, aliases = es.send("GET", f"/_alias/{p['index']}")
        c.check(status == 200 and list(aliases) == [p["new"]], f"{p['index']} is now an alias of {p['new']} only",
                f"HTTP {status}: {str(aliases)[:200]}")
        if status != 200:
            return
        es.send("POST", f"/{p['index']}/_refresh")
        c.equal(es.get(f"/{p['index']}/_count")["count"], len(p["docs"]), "all documents are there")
        left = es.post(f"/{p['index']}/_count", {"query": {"term": {"title": p["wrong"]}}})["count"]
        want = sum(d["title"] in (p["wrong"], p["right"]) for d in p["docs"])
        got = es.post(f"/{p['index']}/_count", {"query": {"term": {"title": p["right"]}}})["count"]
        c.equal((left, got), (0, want), f'the title is corrected to "{p["right"]}" everywhere')
