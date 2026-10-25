import json

from lib.tasklib import Task, field_mapping, same_analysis

EXTRA_STOPWORDS = ["very", "just", "really", "also", "quite", "still"]
SYMBOLS = {"&": "and", "+": "plus", "@": "at", "%": "percent"}
TEXTS = [
    "<p>The <b>Running</b> &amp; Jumping Shoes</p>",
    "Café crème & croissants are really quite tasty",
    "An apple + a banana: 100 % natural, just like the bananas",
    "Contact @ the shop: we also deliver flowers & plants",
    "Naïve résumé writers still struggle with déjà vu",
]


class CustomAnalyzer(Task):
    id = "data-custom-analyzer"
    title = "Build a custom analyzer from char filters, tokenizer and token filters"
    covers = ["data.analysis.custom-analyzer", "data.analysis.specify-analyzer", "data.analysis.analyze-api",
              "data.analysis.char-filter.html-strip", "data.analysis.char-filter.mapping",
              "data.analysis.tokenizer.standard", "data.analysis.filter.lowercase",
              "data.analysis.filter.asciifolding", "data.analysis.filter.stop", "data.analysis.filter.stemmer",
              "ingest.mapping.param.analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        symbols = rnd.sample(sorted(SYMBOLS), 2)
        return {"index": f"articles-{iid}", "analyzer": "article_text",
                "symbols": {s: SYMBOLS[s] for s in symbols},
                "stopwords": ["the", "a", "an"] + rnd.sample(EXTRA_STOPWORDS, 2),
                "stemmer": rnd.choice(["english", "light_english", "minimal_english"])}

    def prompt(self, ctx):
        p = ctx.p
        symbols = " and ".join(f'"{s}" with the word "{w}"' for s, w in p["symbols"].items())
        return f"""
Create the index `{p['index']}` with a custom analyzer named `{p['analyzer']}` that, in this order:

  1. removes HTML tags (and decodes entities like &amp;)
  2. replaces {symbols}
  3. splits the text into words like the standard tokenizer does
  4. lowercases them
  5. turns accented characters into plain ASCII (é -> e)
  6. removes the stop words: {', '.join(p['stopwords'])}
  7. reduces words to their stem with the "{p['stemmer']}" stemmer

Map a text field `body` that uses this analyzer, both when indexing and when searching.
Test it with the _analyze API.
"""

    def definition(self, p):
        return {
            "analysis": {
                "char_filter": {"symbols": {"type": "mapping",
                                            "mappings": [f"{s} => {w}" for s, w in p["symbols"].items()]}},
                "filter": {"my_stop": {"type": "stop", "stopwords": p["stopwords"]},
                           "my_stemmer": {"type": "stemmer", "language": p["stemmer"]}},
                "analyzer": {p["analyzer"]: {"type": "custom", "char_filter": ["html_strip", "symbols"],
                                             "tokenizer": "standard",
                                             "filter": ["lowercase", "asciifolding", "my_stop", "my_stemmer"]}},
            }
        }

    def solution(self, ctx):
        p = ctx.p
        mappings = ",\n            ".join(f'"{s} => {w}"' for s, w in p["symbols"].items())
        return f"""
PUT {p['index']}
{{
  "settings": {{
    "analysis": {{
      "char_filter": {{
        "symbols": {{
          "type": "mapping",
          "mappings": [
            {mappings}
          ]
        }}
      }},
      "filter": {{
        "my_stop": {{ "type": "stop", "stopwords": {json.dumps(p['stopwords'])} }},
        "my_stemmer": {{ "type": "stemmer", "language": "{p['stemmer']}" }}
      }},
      "analyzer": {{
        "{p['analyzer']}": {{
          "type": "custom",
          "char_filter": ["html_strip", "symbols"],
          "tokenizer": "standard",
          "filter": ["lowercase", "asciifolding", "my_stop", "my_stemmer"]
        }}
      }}
    }}
  }},
  "mappings": {{
    "properties": {{
      "body": {{ "type": "text", "analyzer": "{p['analyzer']}" }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        mapping = field_mapping(es, p["index"], "body")
        if not c.check(mapping is not None, f"index {p['index']} has a body field"):
            return
        c.equal(mapping.get("analyzer"), p["analyzer"], f"body uses the {p['analyzer']} analyzer")
        c.check(mapping.get("search_analyzer") in (None, p["analyzer"]), "and searches with it too",
                f"search_analyzer is {mapping.get('search_analyzer')}")
        reference = f"ref-{ctx.iid}"
        es.send("DELETE", f"/{reference}")
        es.put(f"/{reference}", {"settings": self.definition(p)})
        try:
            same_analysis(c, es, p["index"], reference, TEXTS, f"{p['analyzer']} produces the expected tokens",
                          analyzer=p["analyzer"])
        finally:
            es.send("DELETE", f"/{reference}")
