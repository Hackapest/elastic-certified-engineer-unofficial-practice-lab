import json

from lib.tasklib import Task, field_mapping, temp_copy

DOCS = ["Running shoes for trail runners", "The runner's guide to shoes", "Shoe care for running",
        "Trail running shoe review", "Ran out of shoes"]


class SearchQuoteAnalyzer(Task):
    id = "data-search-quote-analyzer"
    title = "Stemmed searches, but exact phrases in quotes"
    covers = ["search.fulltext.search-analysis", "data.analysis.specify-analyzer", "data.analysis.custom-analyzer",
              "data.analysis.filter.keyword-repeat", "data.analysis.filter.porter-stem",
              "data.analysis.filter.remove-duplicates", "search.fulltext.query-string",
              "ingest.mapping.param.search-analyzer"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"articles-q-{iid}", "field": rnd.choice(["title", "headline"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create the index `{p['index']}` with a text field `{p['field']}` where searches are stemmed (so "running"
also finds "runs" and "run"). But when users put a phrase in double quotes in a query_string
query, the quoted words must match exactly as written, without stemming:

  query_string  running shoes        finds "Trail running shoe review" (stemmed)
  query_string  "running shoes"      finds "Running shoes for trail runners", but not
                                     "Trail running shoe review"

Solve it in the mapping, so users don't need special query options.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# Index both the stemmed and the original form of every word (keyword_repeat), search
# unquoted words stemmed, and quoted phrases with the original words only.
PUT {p['index']}
{{
  "settings": {{
    "analysis": {{
      "analyzer": {{
        "stemmed_and_exact": {{
          "tokenizer": "standard",
          "filter": ["lowercase", "keyword_repeat", "porter_stem", "remove_duplicates"]
        }},
        "stemmed": {{
          "tokenizer": "standard",
          "filter": ["lowercase", "porter_stem"]
        }}
      }}
    }}
  }},
  "mappings": {{
    "properties": {{
      "{p['field']}": {{
        "type": "text",
        "analyzer": "stemmed_and_exact",
        "search_analyzer": "stemmed",
        "search_quote_analyzer": "standard"
      }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        mapping = field_mapping(es, p["index"], p["field"])
        if not c.check(mapping is not None, f"index {p['index']} has a field {p['field']}"):
            return
        test = f"verify-{ctx.iid}"
        es.send("DELETE", f"/{test}")
        error = temp_copy(es, p["index"], test)
        if not c.check(error is None, "the index can be tested", error):
            return
        try:
            bulk = "".join(json.dumps({"index": {"_id": str(i)}}) + "\n" + json.dumps({p["field"]: d}) + "\n"
                           for i, d in enumerate(DOCS))
            es.send("POST", f"/{test}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

            def found(query):
                hits = es.post(f"/{test}/_search", {"query": {"query_string": {"default_field": p["field"],
                                                                               "query": query}}})["hits"]["hits"]
                return sorted(DOCS[int(h["_id"])] for h in hits)
            stemmed = found("running shoes")
            c.check("Trail running shoe review" in stemmed and "Shoe care for running" in stemmed,
                    "unquoted words are stemmed", f"running shoes found: {stemmed}")
            exact = found('"running shoes"')
            c.equal(exact, ["Running shoes for trail runners"], "quoted phrases match the exact words only")
        finally:
            es.send("DELETE", f"/{test}")
