import json

from lib.tasklib import Task, field_mapping, same_analysis

TEXTS = [
    "XR-2000b Turbo Pump",
    "invoice_2025-10.final.PDF report.docx",
    "an ox is not a pneumatic compressor or a compression fitting, compressors compressors compressors",
    "Stainless steel hex bolts M8 x 40",
    "a b c dd eee ffff ggggg hhhhhh",
    "alpha bravo charlie delta echo foxtrot golf hotel india juliett kilo",
]


class PartialMatchFilters(Task):
    id = "data-partial-match-filters"
    title = "N-grams, reversed tokens and token length/count filters for partial matching"
    covers = ["data.analysis.tokenizer.ngram", "data.analysis.filter.ngram", "data.analysis.filter.reverse",
              "data.analysis.filter.length", "data.analysis.filter.truncate", "data.analysis.filter.unique",
              "data.analysis.filter.limit", "data.analysis.tokenizer.whitespace", "data.analysis.custom-analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        gram_min = rnd.choice([2, 3])
        return {"index": f"spareparts-{iid}", "gram_min": gram_min, "gram_max": gram_min + rnd.choice([0, 1]),
                "tri": rnd.choice([3, 4]), "len_min": rnd.choice([2, 3]), "len_max": rnd.choice([12, 15]),
                "truncate": rnd.choice([6, 8]), "limit": rnd.choice([5, 8])}

    def definition(self, p):
        return {
            "settings": {
                "index.max_ngram_diff": 1,
                "analysis": {
                    "tokenizer": {"sku_grams": {"type": "ngram", "min_gram": p["gram_min"], "max_gram": p["gram_max"],
                                                "token_chars": ["letter", "digit"]}},
                    "filter": {
                        "grams": {"type": "ngram", "min_gram": p["tri"], "max_gram": p["tri"]},
                        "len": {"type": "length", "min": p["len_min"], "max": p["len_max"]},
                        "cut": {"type": "truncate", "length": p["truncate"]},
                        "first_n": {"type": "limit", "max_token_count": p["limit"]},
                    },
                    "analyzer": {
                        "sku_infix": {"type": "custom", "tokenizer": "sku_grams", "filter": ["lowercase"]},
                        "reversed": {"type": "custom", "tokenizer": "whitespace", "filter": ["lowercase", "reverse"]},
                        "word_grams": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "grams"]},
                        "short_keywords": {"type": "custom", "tokenizer": "standard",
                                           "filter": ["lowercase", "len", "cut", "unique", "first_n"]},
                    },
                },
            },
            "mappings": {"properties": {
                "sku": {"type": "text", "analyzer": "sku_infix"},
                "filename": {"type": "text", "analyzer": "reversed"},
                "description": {"type": "text", "analyzer": "word_grams"},
                "keywords": {"type": "text", "analyzer": "short_keywords"},
            }},
        }

    def prompt(self, ctx):
        p = ctx.p
        grams = f"{p['gram_min']}" if p["gram_min"] == p["gram_max"] else f"{p['gram_min']} to {p['gram_max']}"
        return f"""
Create the index `{p['index']}` for a spare parts catalog with these text fields:

  sku          for infix search: the text is cut into all character n-grams of {grams} characters,
               built only from letters and digits (any other character separates them), lowercased.
               Do this in the tokenizer.
  filename     split on whitespace only, lowercased, and every token stored reversed
               ("report.pdf" -> "fdp.troper"), so suffix searches become prefix searches
  description  split like the standard tokenizer, lowercased, and every word then cut into its
               n-grams of exactly {p['tri']} characters by a token filter
  keywords     split like the standard tokenizer and lowercased; then, in this order: drop tokens
               shorter than {p['len_min']} or longer than {p['len_max']} characters, cut the remaining tokens to
               at most {p['truncate']} characters, remove duplicate tokens, and keep only the first {p['limit']} tokens

Test the fields with the _analyze API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{json.dumps(self.definition(p), indent=2)}

POST {p['index']}/_analyze
{{ "field": "keywords", "text": "compressors compressor compression fitting" }}
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
