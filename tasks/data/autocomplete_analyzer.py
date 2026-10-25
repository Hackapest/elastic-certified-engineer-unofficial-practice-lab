from lib.tasklib import Task, analyze, field_mapping

TEXTS = ["Laptop Pro 15", "Wireless-Mouse", "USB-C Docking Station", "Noise Cancelling Headphones"]


class AutocompleteAnalyzer(Task):
    id = "data-autocomplete-analyzer"
    title = "Search-as-you-type with edge n-grams and a separate search analyzer"
    covers = ["data.analysis.filter.edge-ngram", "data.analysis.tokenizer.edge-ngram",
              "data.analysis.specify-analyzer", "data.analysis.custom-analyzer",
              "ingest.mapping.param.search-analyzer", "ingest.mapping.param.analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"products-ac-{iid}", "min": rnd.choice([1, 2, 3]), "max": rnd.choice([8, 10, 15])}

    def prompt(self, ctx):
        p = ctx.p
        example = ", ".join(f'"{"laptop"[:n]}"' for n in range(p["min"], min(p["max"], 6) + 1))
        return f"""
Create the index `{p['index']}` for a search box that suggests products while the user types.
It has one text field, `name`:

  - When indexing, each word of the name (split like the standard tokenizer, lowercased) must
    also be stored as all its prefixes of {p['min']} to {p['max']} characters: "Laptop" -> {example}
  - When searching, the user's input must NOT be split into prefixes: it is only split into words
    and lowercased (so "lapt" finds "Laptop Pro", but "lpx" finds nothing).

Test the index-time analysis with the _analyze API on the field.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "settings": {{
    "analysis": {{
      "filter": {{
        "prefixes": {{ "type": "edge_ngram", "min_gram": {p['min']}, "max_gram": {p['max']} }}
      }},
      "analyzer": {{
        "autocomplete": {{
          "type": "custom",
          "tokenizer": "standard",
          "filter": ["lowercase", "prefixes"]
        }}
      }}
    }}
  }},
  "mappings": {{
    "properties": {{
      "name": {{
        "type": "text",
        "analyzer": "autocomplete",
        "search_analyzer": "standard"
      }}
    }}
  }}
}}
"""

    @staticmethod
    def expected_index_tokens(p, text):
        words = [w.lower() for w in text.replace("-", " ").split()]
        return [w[:n] for w in words for n in range(p["min"], min(p["max"], len(w)) + 1)]

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        mapping = field_mapping(es, p["index"], "name")
        if not c.check(mapping is not None, f"index {p['index']} has a name field"):
            return
        problem = None
        for text in TEXTS:
            got = analyze(es, p["index"], text, field="name")
            if sorted(got or []) != sorted(self.expected_index_tokens(p, text)):
                problem = f"for {text!r}: expected {self.expected_index_tokens(p, text)}, got {got}"
                break
        c.check(problem is None, "indexing stores the lowercased prefixes of each word", problem)

        search_analyzer = mapping.get("search_analyzer")
        if not c.check(search_analyzer, "name has a separate search analyzer",
                       "without search_analyzer, the query is split into prefixes too"):
            return
        problem = None
        for text in TEXTS:
            got = analyze(es, p["index"], text, analyzer=search_analyzer)
            want = [w.lower() for w in text.replace("-", " ").split()]
            if got != want:
                problem = f"for {text!r}: expected {want}, got {got}"
                break
        c.check(problem is None, "searching only splits into lowercased words", problem)
