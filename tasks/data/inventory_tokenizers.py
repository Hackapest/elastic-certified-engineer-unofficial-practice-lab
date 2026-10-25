import json

from lib.tasklib import Task, field_mapping, same_analysis

TEXTS = [
    "/srv/data/backups/db-01/2025-10-01.tar.gz",
    "Contact ops@example.com or see https://wiki.example.com/assets?id=ABC-1234 for details",
    "rack-12,  row:4;Cold-Aisle  eu-west-1.prod",
    "Assets ABC-1234 and xyz-9999, DEF-0042b and GHI-77",
    "Dell_PowerEdge_R750 server__rev2",
    "WEB-01.Example.COM",
]


class InventoryTokenizers(Task):
    id = "data-inventory-tokenizers"
    title = "Pick the right tokenizer for technical fields (paths, emails, codes, labels)"
    covers = ["data.analysis.tokenizer.path-hierarchy", "data.analysis.tokenizer.uax-url-email",
              "data.analysis.tokenizer.char-group", "data.analysis.tokenizer.pattern",
              "data.analysis.tokenizer.simple-pattern", "data.analysis.tokenizer.simple-pattern-split",
              "data.analysis.tokenizer.letter", "data.analysis.tokenizer.lowercase",
              "data.analysis.tokenizer.keyword",
              "data.analysis.filter.uppercase", "data.analysis.custom-analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"assets-{iid}", "skip": rnd.choice([0, 1]), "case": rnd.choice(["upper", "lower"]),
                "label_chars": rnd.choice([[",", ";"], [",", ";", ":"]])}

    def definition(self, p):
        case_filter = "uppercase" if p["case"] == "upper" else "lowercase"
        return {
            "settings": {"analysis": {
                "tokenizer": {
                    "paths": {"type": "path_hierarchy", "delimiter": "/", "skip": p["skip"]},
                    "labels": {"type": "char_group", "tokenize_on_chars": ["whitespace"] + p["label_chars"]},
                    "codes": {"type": "pattern", "pattern": "[A-Z]{3}-[0-9]{4}", "group": 0},
                    "underscores": {"type": "simple_pattern_split", "pattern": "_"},
                },
                "analyzer": {
                    "path_analyzer": {"type": "custom", "tokenizer": "paths"},
                    "contact_analyzer": {"type": "custom", "tokenizer": "uax_url_email", "filter": ["lowercase"]},
                    "label_analyzer": {"type": "custom", "tokenizer": "labels", "filter": ["lowercase"]},
                    "code_analyzer": {"type": "custom", "tokenizer": "codes"},
                    "vendor_analyzer": {"type": "custom", "tokenizer": "letter", "filter": [case_filter]},
                    "model_analyzer": {"type": "custom", "tokenizer": "underscores"},
                    "host_analyzer": {"type": "custom", "tokenizer": "keyword", "filter": ["lowercase"]},
                },
            }},
            "mappings": {"properties": {
                "path": {"type": "text", "analyzer": "path_analyzer"},
                "contact": {"type": "text", "analyzer": "contact_analyzer"},
                "labels": {"type": "text", "analyzer": "label_analyzer"},
                "codes": {"type": "text", "analyzer": "code_analyzer"},
                "vendor": {"type": "text", "analyzer": "vendor_analyzer"},
                "model": {"type": "text", "analyzer": "model_analyzer"},
                "host": {"type": "text", "analyzer": "host_analyzer"},
            }},
        }

    def prompt(self, ctx):
        p = ctx.p
        path = ("/srv/data/backups -> /srv, /srv/data, /srv/data/backups" if p["skip"] == 0 else
                "/srv/data/backups -> /data, /data/backups (the first component, the mount point, is skipped)")
        chars = " ".join(f'"{ch}"' for ch in p["label_chars"])
        return f"""
Create the index `{p['index']}` for an IT asset inventory, with these text fields. Each field
needs its own analyzer (name them as you like):

  path     a file path, indexed as all its parent paths: {path}
  contact  free text where URLs and email addresses stay whole tokens; other words are split
           like the standard tokenizer does; everything lowercased
  labels   split only at whitespace and the characters {chars}; hyphens, dots and other
           characters stay inside the tokens; lowercased
  codes    only asset codes are kept as tokens: exactly three capital letters, a hyphen and four
           digits (e.g. ABC-1234); all other text is dropped, and a code is matched wherever it occurs
  vendor   split at every character that is not a letter, then {p['case']}cased
  model    split only at underscores (no empty tokens, case unchanged)
  host     the whole value as a single lowercased token

Test each field with the _analyze API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{json.dumps(self.definition(p), indent=2)}

POST {p['index']}/_analyze
{{ "field": "path", "text": "/srv/data/backups/db-01" }}
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
