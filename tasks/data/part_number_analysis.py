import json

from lib.tasklib import Task, field_mapping, same_analysis

TEXTS = [
    "PN: XR-2000b PowerShot",
    "pn:ab12cd-7 Wi-Fi",
    "+49 (0)30 1234-567",
    "support.team2@example.co.uk",
    "SD500 Extreme-Pro",
]


class PartNumberAnalysis(Task):
    id = "data-part-number-analysis"
    title = "Analyze part numbers, phone numbers and emails with pattern-based filters"
    covers = ["data.analysis.char-filter.pattern-replace", "data.analysis.filter.word-delimiter-graph",
              "data.analysis.filter.flatten-graph", "data.analysis.filter.pattern-replace",
              "data.analysis.filter.pattern-capture", "data.analysis.tokenizer.whitespace",
              "data.analysis.tokenizer.keyword", "data.analysis.custom-analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"partnumbers-{iid}", "prefix": rnd.choice(["PN", "REF", "ART"]),
                "catenate": rnd.choice(["all", "words"])}

    def definition(self, p):
        wdg = {"type": "word_delimiter_graph", "preserve_original": True}
        if p["catenate"] == "all":
            wdg["catenate_all"] = True
        else:
            wdg["catenate_words"] = True
        return {
            "settings": {"analysis": {
                "char_filter": {"strip_prefix": {"type": "pattern_replace", "pattern": f"(?i)\\b{p['prefix']}:\\s*",
                                                 "replacement": ""}},
                "filter": {
                    "parts": wdg,
                    "digits_only": {"type": "pattern_replace", "pattern": "[^0-9]", "replacement": ""},
                    "email_parts": {"type": "pattern_capture", "preserve_original": True,
                                    "patterns": ["^([^@]+)@", "@(.+)$"]},
                },
                "analyzer": {
                    "part_number": {"type": "custom", "char_filter": ["strip_prefix"], "tokenizer": "whitespace",
                                    "filter": ["parts", "flatten_graph", "lowercase"]},
                    "phone": {"type": "custom", "tokenizer": "keyword", "filter": ["digits_only"]},
                    "email": {"type": "custom", "tokenizer": "keyword", "filter": ["lowercase", "email_parts"]},
                },
            }},
            "mappings": {"properties": {
                "part_number": {"type": "text", "analyzer": "part_number"},
                "phone": {"type": "text", "analyzer": "phone"},
                "email": {"type": "text", "analyzer": "email"},
            }},
        }

    def prompt(self, ctx):
        p = ctx.p
        catenate = ("all the parts (letters and digits) joined into one extra token: XR-2000b -> xr2000b"
                    if p["catenate"] == "all" else
                    "runs of letter-only parts joined into one extra token: Wi-Fi -> wifi")
        return f"""
Create the index `{p['index']}` with three text fields for a parts catalog:

  part_number  Values may start with the prefix "{p['prefix']}:" in any letter case, optionally followed by
               spaces; remove it before tokenizing. Then split on whitespace, and split each token
               further at hyphens, case changes and letter/digit transitions (word_delimiter_graph),
               keeping the original token and also indexing {catenate}. This is an index-time analyzer,
               so the token graph must be flattened. Lowercase at the end.
  phone        the whole value as one single token that keeps only the digits:
               "+49 (0)30 12-34" -> "490301234"
  email        the whole lowercased email address as one token, plus the part before the "@" and the
               part after it as extra tokens

Test the fields with the _analyze API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{json.dumps(self.definition(p), indent=2)}

POST {p['index']}/_analyze
{{ "field": "part_number", "text": "{p['prefix']}: XR-2000b PowerShot" }}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        fields = list(self.definition(p)["mappings"]["properties"])
        missing = [f for f in fields if field_mapping(es, p["index"], f) is None]
        if not c.check(not missing, f"index {p['index']} has the fields {', '.join(fields)}",
                       f"missing: {', '.join(missing)}"):
            return
        texts = TEXTS + [f"{p['prefix'].lower()}:  QX-15a", f"{p['prefix']}:ZZ9-Plural"]
        reference = f"ref-{ctx.iid}"
        es.send("DELETE", f"/{reference}")
        es.put(f"/{reference}", self.definition(p))
        try:
            for field in fields:
                same_analysis(c, es, p["index"], reference, texts, f"{field} is analyzed as requested", field=field)
        finally:
            es.send("DELETE", f"/{reference}")
