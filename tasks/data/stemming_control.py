import json

from lib.tasklib import Task, field_mapping, same_analysis

TEXTS = [
    "Running shoes for runners who love running",
    "The mice and geese ate generously at the Skiing Festival",
    "Happiness is found in organized boxes of flies",
    "Leaves of the trees; feet of the children",
    "Universal universities and their universes",
]
STEMMERS = {
    "Snowball (English)": {"type": "snowball", "language": "English"},
    "Porter (porter_stem)": {"type": "porter_stem"},
    "KStem": {"type": "kstem"},
}
PROTECTED = [["skiing", "running"], ["universities", "organized"], ["happiness", "skiing"]]
OVERRIDES = [{"mice": "mouse", "geese": "goose"}, {"feet": "foot", "children": "child"},
             {"leaves": "leaf", "mice": "mouse"}]


class StemmingControl(Task):
    id = "data-stemming-control"
    title = "Control stemming: algorithmic stemmers, protected words, overrides, keeping the original"
    covers = ["data.analysis.filter.snowball", "data.analysis.filter.porter-stem", "data.analysis.filter.kstem",
              "data.analysis.filter.keyword-marker", "data.analysis.filter.stemmer-override",
              "data.analysis.filter.keyword-repeat", "data.analysis.filter.remove-duplicates",
              "data.analysis.custom-analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"catalog-stem-{iid}", "stemmer": rnd.choice(sorted(STEMMERS)),
                "protected": rnd.choice(PROTECTED), "overrides": rnd.choice(OVERRIDES)}

    def definition(self, p):
        return {
            "settings": {"analysis": {
                "filter": {
                    "my_stemmer": STEMMERS[p["stemmer"]],
                    "protect": {"type": "keyword_marker", "keywords": p["protected"]},
                    "overrides": {"type": "stemmer_override",
                                  "rules": [f"{k} => {v}" for k, v in p["overrides"].items()]},
                },
                "analyzer": {
                    "name_text": {"type": "custom", "tokenizer": "standard",
                                  "filter": ["lowercase", "overrides", "protect", "my_stemmer"]},
                    "both_forms": {"type": "custom", "tokenizer": "standard",
                                   "filter": ["lowercase", "keyword_repeat", "my_stemmer", "remove_duplicates"]},
                },
            }},
            "mappings": {"properties": {
                "name": {"type": "text", "analyzer": "name_text"},
                "description": {"type": "text", "analyzer": "both_forms"},
            }},
        }

    def prompt(self, ctx):
        p = ctx.p
        rules = ", ".join(f'"{k}" -> "{v}"' for k, v in p["overrides"].items())
        return f"""
Create the index `{p['index']}` with two text fields. Both split text like the standard tokenizer,
lowercase it, and stem with the {p['stemmer']} stemmer token filter, but:

  name         the words {' and '.join(p['protected'])} must never be stemmed, and these irregular
               forms must be replaced by fixed stems instead of going through the stemmer: {rules}
  description  every word must be indexed both in its original (lowercased) form and in its stemmed
               form, at the same position; when both forms are identical, the token appears only once

Use the _analyze API to compare the two fields on "Running shoes for runners".
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{json.dumps(self.definition(p), indent=2)}

POST {p['index']}/_analyze
{{ "field": "description", "text": "Running shoes for runners" }}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        fields = list(self.definition(p)["mappings"]["properties"])
        missing = [f for f in fields if field_mapping(es, p["index"], f) is None]
        if not c.check(not missing, f"index {p['index']} has the fields {', '.join(fields)}",
                       f"missing: {', '.join(missing)}"):
            return
        reference = f"ref-{ctx.iid}"
        es.send("DELETE", f"/{reference}")
        es.put(f"/{reference}", self.definition(p))
        try:
            for field in fields:
                same_analysis(c, es, p["index"], reference, TEXTS, f"{field} is analyzed as requested", field=field)
        finally:
            es.send("DELETE", f"/{reference}")
