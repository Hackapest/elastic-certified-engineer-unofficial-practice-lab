import json

from lib.tasklib import Task, field_mapping, same_analysis

TEXTS = [
    "The Best Lemon-Pie of 2025, with Mrs. O'Brien's crust",
    "flour, sugar; butter , eggs;LEMON zest",
    "quick EASY vegan quick dessert",
    "ID-4711/b and the rest",
    "Tomato soup: tomatoes, onion and a pinch of salt",
]
STOPWORD_SETS = [["the", "of", "with", "and", "a"], ["the", "a", "an", "and", "or", "of"]]
SEPARATORS = {"comma or semicolon": r"\s*[,;]\s*", "comma, semicolon or colon": r"\s*[,;:]\s*"}


class BuiltinAnalyzers(Task):
    id = "data-builtin-analyzers"
    title = "Choose and configure built-in analyzers per field"
    covers = ["data.analysis.configure-builtin", "data.analysis.analyzer.standard", "data.analysis.analyzer.simple",
              "data.analysis.analyzer.whitespace", "data.analysis.analyzer.stop", "data.analysis.analyzer.keyword",
              "data.analysis.analyzer.pattern", "data.analysis.analyzer.fingerprint", "data.analysis.analyze-api",
              "data.analysis.specify-analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"recipes-{iid}", "stopwords": rnd.choice(STOPWORD_SETS), "max_len": rnd.choice([5, 6, 8]),
                "separator": rnd.choice(sorted(SEPARATORS)), "fp_sep": rnd.choice(["-", "_", "+"])}

    def definition(self, p):
        return {
            "settings": {"analysis": {"analyzer": {
                "title_text": {"type": "standard", "stopwords": p["stopwords"], "max_token_length": p["max_len"]},
                "ingredient_list": {"type": "pattern", "pattern": SEPARATORS[p["separator"]], "lowercase": True},
                "tag_dedup": {"type": "fingerprint", "separator": p["fp_sep"]},
            }}},
            "mappings": {"properties": {
                "title": {"type": "text", "analyzer": "title_text"},
                "ingredients": {"type": "text", "analyzer": "ingredient_list"},
                "tags": {"type": "text", "analyzer": "whitespace"},
                "recipe_id": {"type": "text", "analyzer": "keyword"},
                "author": {"type": "text", "analyzer": "simple"},
                "notes": {"type": "text", "analyzer": "stop"},
                "tag_set": {"type": "text", "analyzer": "tag_dedup"},
            }},
        }

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create the index `{p['index']}` with these text fields. Use only built-in analyzers: either as they
are, or by defining a configured instance of a built-in analyzer type in the index settings
(no custom analyzers built from a tokenizer and filters).

  title        like the standard analyzer, but removing the stop words {', '.join(p['stopwords'])}
               and splitting tokens longer than {p['max_len']} characters
  ingredients  one lowercased token per ingredient: the text is split only at a {p['separator']}
               (with any surrounding whitespace), so "Lemon zest, Sugar" gives "lemon zest" and "sugar"
  tags         split on whitespace only, case and punctuation kept
  recipe_id    the whole value as one single token, unchanged
  author       split at every non-letter character and lowercased
  notes        split at every non-letter character, lowercased, English stop words removed
  tag_set      a single token made of the sorted, de-duplicated, lowercased, ASCII-folded words,
               joined with "{p['fp_sep']}" (e.g. "quick vegan Quick" gives "quick{p['fp_sep']}vegan")

Check each field with the _analyze API.
"""

    def solution(self, ctx):
        p = ctx.p
        d = self.definition(p)
        return f"""
PUT {p['index']}
{json.dumps(d, indent=2)}

POST {p['index']}/_analyze
{{ "field": "ingredients", "text": "flour, sugar; butter , eggs" }}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        fields = list(self.definition(p)["mappings"]["properties"])
        missing = [f for f in fields if field_mapping(es, p["index"], f) is None]
        if not c.check(not missing, f"index {p['index']} has the fields {', '.join(fields)}",
                       f"missing: {', '.join(missing)}"):
            return
        status, response = es.send("GET", f"/{p['index']}/_settings?filter_path=**.analysis.analyzer")
        analyzers = next(iter((response or {}).values()), {}).get("settings", {}).get("index", {}) \
            .get("analysis", {}).get("analyzer", {}) if status == 200 and response else {}
        custom = [n for n, a in analyzers.items() if a.get("type") == "custom" or "tokenizer" in a]
        c.check(not custom, "only built-in analyzer types are used", f"custom analyzers: {', '.join(custom)}")
        reference = f"ref-{ctx.iid}"
        es.send("DELETE", f"/{reference}")
        es.put(f"/{reference}", self.definition(p))
        try:
            for field in fields:
                same_analysis(c, es, p["index"], reference, TEXTS, f"{field} is analyzed as requested", field=field)
        finally:
            es.send("DELETE", f"/{reference}")
