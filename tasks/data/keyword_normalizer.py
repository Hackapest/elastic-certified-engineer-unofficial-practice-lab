import json

from lib.tasklib import Task, field_mapping, temp_copy

VALUES = ["ABC-123", "abc-123", "  Ábc-123 ", "Straße-9", "STRASSE-9", "Crème-Brûlée"]


class KeywordNormalizer(Task):
    id = "data-keyword-normalizer"
    title = "Case- and accent-insensitive exact matching with a normalizer"
    covers = ["data.analysis.normalizer", "ingest.mapping.param.normalizer", "ingest.types.keyword",
              "data.analysis.filter.lowercase", "data.analysis.filter.asciifolding", "data.analysis.filter.trim"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"parts-{iid}", "field": rnd.choice(["sku", "part_number", "code"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create the index `{p['index']}` with a keyword field `{p['field']}`. Exact-match queries, sorting and
aggregations on it must ignore upper/lower case, accents and leading or trailing spaces:
a term query for "abc-123" must find documents with "ABC-123", "  Ábc-123 " and "abc-123", and
a terms aggregation must count them as one value.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "settings": {{
    "analysis": {{
      "normalizer": {{
        "folded": {{
          "type": "custom",
          "filter": ["trim", "lowercase", "asciifolding"]
        }}
      }}
    }}
  }},
  "mappings": {{
    "properties": {{
      "{p['field']}": {{ "type": "keyword", "normalizer": "folded" }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        mapping = field_mapping(es, p["index"], p["field"])
        if not c.check(mapping is not None, f"index {p['index']} has a {p['field']} field"):
            return
        c.equal(mapping.get("type"), "keyword", f"{p['field']} is a keyword field")
        test = f"verify-{ctx.iid}"
        es.send("DELETE", f"/{test}")
        error = temp_copy(es, p["index"], test)
        if not c.check(error is None, "the index can be tested", error):
            return
        try:
            bulk = "".join(json.dumps({"index": {}}) + "\n" + json.dumps({p["field"]: v}) + "\n" for v in VALUES)
            es.send("POST", f"/{test}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")
            found = es.post(f"/{test}/_search", {"query": {"term": {p["field"]: "abc-123"}}})["hits"]["total"]["value"]
            c.equal(found, 3, 'a term query for "abc-123" finds all three spellings')
            buckets = es.post(f"/{test}/_search", {"size": 0, "aggs": {"v": {"terms": {"field": p["field"]}}}}
                              )["aggregations"]["v"]["buckets"]
            counts = sorted(b["doc_count"] for b in buckets)
            # 3 spellings of abc-123, 2 of strasse-9 (asciifolding turns ß into ss), 1 crème-brûlée
            c.equal(counts, [1, 2, 3], "the aggregation counts the spellings as one value")
        finally:
            es.send("DELETE", f"/{test}")
