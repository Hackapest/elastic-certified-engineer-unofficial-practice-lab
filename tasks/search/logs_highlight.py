import json

from lib.sampledata import LOG_PRODUCTS, LOG_TAGS, LOGS
from lib.tasklib import Task, get, same_hits

FIELDS = ["@timestamp", "request", "response"]


class LogsHighlight(Task):
    id = "search-logs-highlight"
    title = "Highlight matches and return only some fields"
    covers = ["search.results.highlight", "search.results.source-filtering", "search.results.sort",
              "search.fulltext.match", "search.compound.bool"]
    answer = "query"

    def params(self, rnd, iid):
        return {"product": rnd.choice(LOG_PRODUCTS), "tag": rnd.choice(LOG_TAGS),
                "pre": rnd.choice(["<mark>", "<b>", "[[", "**"]), "size": rnd.choice([10, 20, 30])}

    def post(self, pre):
        return {"<mark>": "</mark>", "<b>": "</b>", "[[": "]]", "**": "**"}[pre]

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{LOGS}`, find the {p['size']} most recent log entries (by @timestamp) whose request mentions
"{p['product']}" (full-text match on the request field) and that have the tag "{p['tag']}"
(tags.keyword).

  - Highlight the matching words in the request field only, wrapped in {p['pre']} and {self.post(p['pre'])}
  - Return only these fields of each document's source: {', '.join(FIELDS)}
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {LOGS}/_search
{{
  "size": {p['size']},
  "_source": {json.dumps(FIELDS)},
  "query": {{
    "bool": {{
      "must": [
        {{ "match": {{ "request": "{p['product']}" }} }}
      ],
      "filter": [
        {{ "term": {{ "tags.keyword": "{p['tag']}" }} }}
      ]
    }}
  }},
  "sort": [{{ "@timestamp": "desc" }}],
  "highlight": {{
    "pre_tags": ["{p['pre']}"],
    "post_tags": ["{self.post(p['pre'])}"],
    "fields": {{ "request": {{}} }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Default <em> tags
        p = ctx.p
        return self.solution(ctx).replace(f'"pre_tags": ["{p["pre"]}"],', "").replace(
            f'"post_tags": ["{self.post(p["pre"])}"],', "")

    def grade(self, ctx, c, answer, reference):
        same_hits(c, answer, reference, ordered=True)
        got = [h.get("highlight") for h in get(answer, "hits.hits", [])]
        want = [h.get("highlight") for h in get(reference, "hits.hits", [])]
        c.check(got == want, "highlights the request field with the requested tags",
                f"first hit's highlight: expected {want[0] if want else None}, got {got[0] if got else None}")
        sources = [set(h.get("_source", {})) for h in get(answer, "hits.hits", [])]
        c.check(sources and all(s == set(FIELDS) for s in sources), "returns only the requested source fields",
                f"fields returned: {sorted(sources[0]) if sources else 'none'}")
