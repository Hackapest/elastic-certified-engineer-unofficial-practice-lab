import json

from lib.tasklib import Task, field_mapping, get, same_analysis

WORDS = ["battery", "screen", "delivery", "price", "camera", "support"]
COMMENTS = [
    "The battery lasts a full day and the screen is bright",
    "Delivery was slow but the price is fair",
    "An excellent camera for the price",
    "Support answered within an hour, the battery was replaced",
    "The screen cracked after a week; support was not helpful",
    "Great camera, terrible battery",
    "Is the delivery free? The price page does not say",
    "Ultrasuperextraordinarily fast delivery",
]
TEXTS = ["The battery is NOT the problem, it is the screen", "Ultrasuperextraordinarily fast delivery!",
         "And then there were none", "Brand-new phone for 499 dollars"]


class CloseReopenAnalyzer(Task):
    id = "data-close-reopen-analyzer"
    title = "Add an analyzer to an existing index (close/open) and apply it to existing documents"
    covers = ["data.index.close-open", "data.analysis.configure-builtin", "data.analysis.analyzer.standard",
              "data.analysis.specify-analyzer", "ingest.reindex.update-by-query-mapping", "ingest.mapping.param.fields"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"reviews-{iid}", "analyzer": rnd.choice(["review_text", "english_words", "clean_text"]),
                "stop": rnd.choice(["_english_", ["the", "a", "an", "is", "was", "and"]]),
                "max_len": rnd.choice([10, 12, 15]), "word": rnd.choice(WORDS)}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"settings": {"number_of_shards": 1, "number_of_replicas": 1},
                                 "mappings": {"properties": {"comment": {"type": "text"}}}})
        bulk = "".join(f'{{"index":{{"_id":"{i}"}}}}\n{json.dumps({"comment": t})}\n' for i, t in enumerate(COMMENTS))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def stop_text(self, p):
        if p["stop"] == "_english_":
            return "the predefined English stop word list"
        return "the stop words " + ", ".join(p["stop"])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds product reviews in the text field `comment`. Without deleting or
recreating the index:

  1. Add an analyzer named `{p['analyzer']}` to the index. It is the built-in standard analyzer,
     configured to remove {self.stop_text(p)}, and to split tokens longer
     than {p['max_len']} characters.
  2. Add a multi-field `comment.clean` that uses this analyzer.
  3. Make sure the documents already in the index are searchable through `comment.clean`, and
     that the index is open and usable again at the end.
"""

    def analysis(self, p):
        return {"analysis": {"analyzer": {p["analyzer"]: {"type": "standard", "stopwords": p["stop"],
                                                          "max_token_length": p["max_len"]}}}}

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST {p['index']}/_close

PUT {p['index']}/_settings
{{
  "analysis": {{
    "analyzer": {{
      "{p['analyzer']}": {{
        "type": "standard",
        "stopwords": {json.dumps(p['stop'])},
        "max_token_length": {p['max_len']}
      }}
    }}
  }}
}}

POST {p['index']}/_open

PUT {p['index']}/_mapping
{{
  "properties": {{
    "comment": {{
      "type": "text",
      "fields": {{
        "clean": {{ "type": "text", "analyzer": "{p['analyzer']}" }}
      }}
    }}
  }}
}}

GET _cluster/health/{p['index']}?wait_for_status=yellow&timeout=30s

POST {p['index']}/_update_by_query?refresh=true
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        state = get(es.send("GET", f"/_cluster/state/metadata/{p['index']}")[1] or {},
                    f"metadata.indices.{p['index']}.state")
        if not c.equal(state, "open", f"index {p['index']} exists and is open"):
            return
        es.send("GET", f"/_cluster/health/{p['index']}?wait_for_status=yellow&timeout=30s")
        count = es.send("GET", f"/{p['index']}/_count")[1] or {}
        c.equal(count.get("count"), len(COMMENTS), "no documents were lost")
        mapping = field_mapping(es, p["index"], "comment.clean")
        if not c.check(mapping is not None, "comment.clean exists"):
            return
        c.equal(mapping.get("analyzer"), p["analyzer"], f"comment.clean uses {p['analyzer']}")
        reference = f"ref-{ctx.iid}"
        es.send("DELETE", f"/{reference}")
        es.put(f"/{reference}", {"settings": self.analysis(p)})
        try:
            same_analysis(c, es, p["index"], reference, TEXTS, f"{p['analyzer']} produces the expected tokens",
                          analyzer=p["analyzer"])
        finally:
            es.send("DELETE", f"/{reference}")
        body = json.dumps({"query": {"match": {"comment.clean": p["word"]}}}).encode()
        got = (es.send("POST", f"/{p['index']}/_count", body, "application/json")[1] or {}).get("count")
        want = sum(p["word"] in t.lower() for t in COMMENTS)
        c.equal(got, want, f"existing documents are searchable through comment.clean (\"{p['word']}\")")
