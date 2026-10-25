import json

from lib.tasklib import Task, field_mapping

TEXTS = [
    "Smart TV with 55 inch screen and Laptop stand",
    "Television mount for the notebook and the cellphone",
    "Mobile phone case, 2 pack, mobile charger included",
    "the quick brown fox jumps over 3 lazy dogs",
    "Gaming Notebook 17 inch, RGB keyboard",
]
SYNONYM_SETS = [
    {"equiv": ["tv", "television"], "oneway": (["notebook", "netbook"], "laptop")},
    {"equiv": ["cellphone", "mobile", "smartphone"], "oneway": (["television", "telly"], "tv")},
    {"equiv": ["laptop", "notebook"], "oneway": (["cellphone", "handy"], "mobile")},
]
ALLOWED_TAGS = [["gaming", "mobile", "smart", "rgb"], ["tv", "laptop", "inch", "pack"], ["phone", "screen", "keyboard", "charger"]]


class InlineSynonymsShingles(Task):
    id = "data-inline-synonyms-shingles"
    title = "Inline synonyms, shingles, keep words and keep types"
    covers = ["data.analysis.filter.synonym", "data.analysis.filter.shingle", "data.analysis.filter.keep-words",
              "data.analysis.filter.keep-types", "data.analysis.custom-analyzer", "ingest.mapping.param.fields"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"electronics-{iid}", "synonyms": rnd.choice(SYNONYM_SETS),
                "shingle_max": rnd.choice([2, 3]), "unigrams": rnd.choice([True, False]),
                "allowed": rnd.choice(ALLOWED_TAGS)}

    def rules(self, p):
        froms, to = p["synonyms"]["oneway"]
        return [", ".join(p["synonyms"]["equiv"]), f"{', '.join(froms)} => {to}"]

    def definition(self, p):
        shingle = {"type": "shingle", "min_shingle_size": 2, "max_shingle_size": p["shingle_max"],
                   "output_unigrams": p["unigrams"]}
        return {
            "settings": {"analysis": {
                "filter": {
                    "product_synonyms": {"type": "synonym", "synonyms": self.rules(p)},
                    "word_pairs": shingle,
                    "allowed_tags": {"type": "keep", "keep_words": p["allowed"]},
                    "numbers_only": {"type": "keep_types", "types": ["<NUM>"]},
                },
                "analyzer": {
                    "product_text": {"type": "custom", "tokenizer": "standard",
                                     "filter": ["lowercase", "product_synonyms"]},
                    "product_shingles": {"type": "custom", "tokenizer": "standard",
                                         "filter": ["lowercase", "word_pairs"]},
                    "tag_list": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "allowed_tags"]},
                    "numbers": {"type": "custom", "tokenizer": "standard", "filter": ["numbers_only"]},
                },
            }},
            "mappings": {"properties": {
                "title": {"type": "text", "analyzer": "product_text",
                          "fields": {"shingles": {"type": "text", "analyzer": "product_shingles"}}},
                "tags": {"type": "text", "analyzer": "tag_list"},
                "sizes": {"type": "text", "analyzer": "numbers"},
            }},
        }

    def prompt(self, ctx):
        p = ctx.p
        equiv = ", ".join(f'"{w}"' for w in p["synonyms"]["equiv"])
        froms, to = p["synonyms"]["oneway"]
        unigrams = ("the single words are indexed as well" if p["unigrams"]
                    else "only the word groups are indexed, not the single words")
        sizes = "2" if p["shingle_max"] == 2 else "2 and 3"
        return f"""
Create the index `{p['index']}` with these fields. All of them split text like the standard tokenizer.

  title           lowercased, with these synonyms defined inline in the index settings (no synonyms
                  set, no file): {equiv} are equivalent and each is expanded to all of them;
                  {' and '.join(f'"{w}"' for w in froms)} are replaced by "{to}"
  title.shingles  a multi-field of title, lowercased, indexing groups of {sizes} consecutive words
                  as single tokens ("smart tv screen" -> "smart tv", ...); {unigrams}
  tags            lowercased, keeping only the words {', '.join(p['allowed'])} (all others dropped)
  sizes           keeping only the tokens that the standard tokenizer classifies as numbers

Test the fields with the _analyze API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{json.dumps(self.definition(p), indent=2)}

POST {p['index']}/_analyze
{{ "field": "title", "text": "Television mount for the notebook" }}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        fields = ["title", "title.shingles", "tags", "sizes"]
        missing = [f for f in fields if field_mapping(es, p["index"], f) is None]
        if not c.check(not missing, f"index {p['index']} has the fields {', '.join(fields)}",
                       f"missing: {', '.join(missing)}"):
            return
        reference = f"ref-{ctx.iid}"
        es.send("DELETE", f"/{reference}")
        es.put(f"/{reference}", self.definition(p))
        try:
            for field in fields:
                same_token_sets(c, es, p["index"], reference, field)
        finally:
            es.send("DELETE", f"/{reference}")


def token_sets(es, index, text, field):
    """Tokens grouped by position, so synonyms listed in another order still compare equal."""
    body = json.dumps({"field": field, "text": text}).encode()
    status, response = es.send("POST", f"/{index}/_analyze", body, "application/json")
    if status != 200:
        return None
    return sorted((t["position"], t["token"]) for t in response.get("tokens", []))


def same_token_sets(c, es, user_index, reference, field):
    for text in TEXTS:
        got, want = token_sets(es, user_index, text, field), token_sets(es, reference, text, field)
        if got != want:
            show = lambda ts: [t for _, t in ts] if ts is not None else None
            return c.fail(f"{field} is analyzed as requested", f"for {text!r}: expected {show(want)}, got {show(got)}")
    return c.check(True, f"{field} is analyzed as requested")
