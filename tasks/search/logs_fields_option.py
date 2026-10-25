from lib.sampledata import LOG_EXTENSIONS, LOGS
from lib.tasklib import Task, get, same_hits

FORMATS = {"yyyy-MM-dd HH:mm": "e.g. 2024-05-17 08:31", "dd/MM/yyyy": "e.g. 17/05/2024",
           "yyyy-MM-dd'T'HH": "e.g. 2024-05-17T08"}
EXTRA = ["geo.dest", "machine.os.keyword", "response.keyword", "host.keyword"]


class LogsFieldsOption(Task):
    id = "search-logs-fields-option"
    title = "Return selected fields with formatting instead of _source (fields, docvalue_fields)"
    covers = ["search.results.fields", "search.results.source-filtering", "search.results.sort"]
    answer = "query"

    def params(self, rnd, iid):
        return {"ext": rnd.choice(LOG_EXTENSIONS), "format": rnd.choice(sorted(FORMATS)), "extra": rnd.choice(EXTRA),
                "size": rnd.choice([5, 10, 20])}

    def wanted(self, p):
        return ["@timestamp", "clientip", p["extra"]]

    def prompt(self, ctx):
        p = ctx.p
        return f"""
A dashboard widget shows the {p['size']} most recent requests in `{LOGS}` for files with the
extension "{p['ext']}" (extension.keyword), newest first (@timestamp).

The widget can't parse _source. Each hit must instead carry exactly these values in its "fields"
section, and nothing else:

  @timestamp   formatted as {p['format']} ({FORMATS[p['format']]})
  clientip
  {p['extra']}

and the hits must not contain _source at all.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {LOGS}/_search
{{
  "size": {p['size']},
  "query": {{ "term": {{ "extension.keyword": "{p['ext']}" }} }},
  "sort": [ {{ "@timestamp": "desc" }} ],
  "_source": false,
  "fields": [
    {{ "field": "@timestamp", "format": "{p['format']}" }},
    "clientip",
    "{p['extra']}"
  ]
}}
"""

    def grade(self, ctx, c, answer, reference):
        if not same_hits(c, answer, reference, ordered=True):
            return
        hits = get(answer, "hits.hits", [])
        c.check(all("_source" not in h for h in hits), "the hits contain no _source",
                "set \"_source\": false")
        want = [h.get("fields") for h in get(reference, "hits.hits", [])]
        got = [h.get("fields") for h in hits]
        detail = None
        for g, w in zip(got, want):
            if g != w:
                detail = f"expected fields {w}, got {g}"
                break
        c.check(got == want, "each hit carries exactly the requested fields, formatted as requested", detail)

    def wrong_answer(self, ctx):
        # The date in its default format
        return self.solution(ctx).replace(f'{{ "field": "@timestamp", "format": "{ctx.p["format"]}" }}', '"@timestamp"')
