import json

from lib.tasklib import Task, field_mapping

TEXTS = [
    "L'avion d'Air France qu'on attendait j'arrive",
    "Istanbul'a gittik, Ankara'dan döndük",
    "IBM and SAP beat Oracle in the EU market",
    "Order ١٢٣ shipped ٤٥ boxes to the UK",
    "Mixed Case BrandName for an ox",
]


class ConditionalTokenFilters(Task):
    id = "data-conditional-token-filters"
    title = "Language clean-up and script-based token filters (elision, apostrophe, condition, multiplexer)"
    covers = ["data.analysis.filter.elision", "data.analysis.filter.apostrophe", "data.analysis.filter.condition",
              "data.analysis.filter.predicate", "data.analysis.filter.multiplexer",
              "data.analysis.filter.decimal-digit", "data.analysis.custom-analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"multilingual-{iid}", "short": rnd.choice([3, 4]), "long": rnd.choice([4, 5, 6]),
                "articles": rnd.choice([["l", "d", "j", "qu"], ["l", "d", "qu"], ["l", "j"]])}

    def definition(self, p):
        return {
            "settings": {"analysis": {
                "filter": {
                    "fr_elision": {"type": "elision", "articles": p["articles"], "articles_case": True},
                    "shout_short": {"type": "condition", "filter": ["uppercase"],
                                    "script": {"source": f"token.getTerm().length() < {p['short']}"}},
                    "long_only": {"type": "predicate_token_filter",
                                  "script": {"source": f"token.getTerm().length() >= {p['long']}"}},
                    "variants": {"type": "multiplexer", "filters": ["lowercase", "lowercase, reverse"]},
                },
                "analyzer": {
                    "french": {"type": "custom", "tokenizer": "standard", "filter": ["fr_elision", "lowercase"]},
                    "turkish_suffix": {"type": "custom", "tokenizer": "standard", "filter": ["apostrophe", "lowercase"]},
                    "acronyms": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "shout_short"]},
                    "long_words": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "long_only"]},
                    "brand_variants": {"type": "custom", "tokenizer": "whitespace", "filter": ["variants"]},
                    "digits": {"type": "custom", "tokenizer": "standard", "filter": ["decimal_digit"]},
                },
            }},
            "mappings": {"properties": {
                "body_fr": {"type": "text", "analyzer": "french"},
                "body_tr": {"type": "text", "analyzer": "turkish_suffix"},
                "headline": {"type": "text", "analyzer": "acronyms"},
                "keywords": {"type": "text", "analyzer": "long_words"},
                "brand": {"type": "text", "analyzer": "brand_variants"},
                "order_text": {"type": "text", "analyzer": "digits"},
            }},
        }

    def prompt(self, ctx):
        p = ctx.p
        articles = ", ".join(f"{a}'" for a in p["articles"])
        return f"""
Create the index `{p['index']}` with these text fields. Unless stated otherwise, text is split like
the standard tokenizer.

  body_fr     remove the French elided articles {articles} (in any letter case) from the start of
              words, then lowercase ("L'avion" -> "avion"); no other articles are removed
  body_tr     remove the apostrophe and everything after it in each token (Turkish suffixes:
              "Istanbul'a" -> "istanbul"), then lowercase
  headline    lowercase everything, then uppercase only the tokens shorter than {p['short']} characters
              (a token filter that applies another filter to some tokens only, decided by a script)
  keywords    lowercase, then keep only tokens of at least {p['long']} characters, decided by a script
  brand       split on whitespace only; index every token at the same position as: the original
              token, its lowercased form, and its lowercased form reversed (no duplicates at a position)
  order_text  digits of any script converted to 0-9 ("١٢٣" -> "123"), case unchanged

Test the fields with the _analyze API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{json.dumps(self.definition(p), indent=2)}

POST {p['index']}/_analyze
{{ "field": "headline", "text": "IBM and SAP beat Oracle" }}
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
                same_token_sets(c, es, p["index"], reference, field)
        finally:
            es.send("DELETE", f"/{reference}")


def token_sets(es, index, text, field):
    """Tokens grouped by position, so filters emitting several tokens per position compare in any order."""
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
