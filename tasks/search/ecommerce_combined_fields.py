from lib.sampledata import ECOMMERCE
from lib.tasklib import Task

# category and manufacturer use the same (standard) analyzer, which combined_fields requires
CATEGORY_WORDS = ["clothing", "shoes", "accessories"]
MAKERS = ["oceanavigations", "elitelligence", "tigress enterprises", "pyramidustries active", "angeldale",
          "low tide media", "spherecords curvy", "gnomehouse"]


class EcommerceCombinedFields(Task):
    id = "search-ecommerce-combined-fields"
    title = "Score several text fields as one (combined_fields)"
    covers = ["search.fulltext.combined-fields"]
    answer = "query"
    compare = "hits_scored"

    def params(self, rnd, iid):
        return {"text": f"{rnd.choice(MAKERS)} {rnd.choice(CATEGORY_WORDS)}",
                "boost": rnd.choice([2, 3]), "top": rnd.choice([10, 20, 25])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{ECOMMERCE}`, customers search for things like "{p['text']}": words that may be spread over the
category (category) and the manufacturer (manufacturer).

Search for "{p['text']}" so that:
  - both fields are treated as if they were ONE combined text field when scoring (term
    frequencies and document frequencies combined across the fields, BM25F), with
    category weighted {p['boost']} times as much as manufacturer;
  - every word must appear, in either field.

Return the {p['top']} best-scoring orders, best first.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": {p['top']},
  "query": {{
    "combined_fields": {{
      "query": "{p['text']}",
      "fields": ["category^{p['boost']}", "manufacturer"],
      "operator": "and"
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # cross_fields blends the fields differently, so the scores differ
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": {p['top']},
  "query": {{
    "multi_match": {{
      "query": "{p['text']}",
      "type": "cross_fields",
      "fields": ["category^{p['boost']}", "manufacturer"],
      "operator": "and"
    }}
  }}
}}
"""
