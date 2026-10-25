import json

from lib.tasklib import Task, field_mapping, get, index_settings
from tasks.search._knowledge_base import ARTICLES, QUESTIONS

ELSER = ".elser-2-elasticsearch"


class ElserPipeline(Task):
    id = "search-elser-pipeline"
    title = "ELSER embeddings through an inference ingest pipeline, searched with sparse_vector"
    covers = ["search.semantic.elser-pipeline", "ingest.pipelines.processor.inference", "ingest.types.sparse-vector",
              "ingest.pipelines.default-final", "search.semantic.inference-endpoint"]
    answer = "state"
    requires = ("ml",)

    def params(self, rnd, iid):
        return {"index": f"faq-{iid}", "pipeline": f"faq-elser-{iid}",
                "field": rnd.choice(["content_embedding", "content_tokens", "ml_terms"]),
                "questions": rnd.sample(range(len(QUESTIONS)), 3)}

    def prompt(self, ctx):
        p = ctx.p
        docs = "\n".join(f"  {json.dumps({'id': a, 'content': b})}" for a, _, b in ARTICLES)
        return f"""
Without semantic_text, build semantic search "by hand" with ELSER (the .elser-2-elasticsearch
inference endpoint; if it isn't running yet: ./ece ml-setup):

  1. An ingest pipeline `{p['pipeline']}` that runs ELSER on the field `content` and stores the result
     in the field `{p['field']}`.
  2. The index `{p['index']}` with `content` (text) and `{p['field']}` mapped for ELSER's output, and the
     pipeline applied automatically to every document indexed into it.
  3. Index these articles (the "id" is the document _id):

{docs}

Then search `{p['field']}` with a sparse_vector query for "{QUESTIONS[p['questions'][0]][0]}".
"""

    def solution(self, ctx):
        p = ctx.p
        bulk = "\n".join(json.dumps({"index": {"_id": a}}) + "\n" + json.dumps({"content": b}) for a, _, b in ARTICLES)
        return f"""
PUT _ingest/pipeline/{p['pipeline']}
{{
  "processors": [
    {{
      "inference": {{
        "model_id": "{ELSER}",
        "input_output": {{ "input_field": "content", "output_field": "{p['field']}" }}
      }}
    }}
  ]
}}

PUT {p['index']}
{{
  "settings": {{ "index.default_pipeline": "{p['pipeline']}" }},
  "mappings": {{
    "properties": {{
      "content": {{ "type": "text" }},
      "{p['field']}": {{ "type": "sparse_vector" }}
    }}
  }}
}}

POST {p['index']}/_bulk?refresh=true
{bulk}

GET {p['index']}/_search
{{
  "query": {{
    "sparse_vector": {{
      "field": "{p['field']}",
      "inference_id": "{ELSER}",
      "query": {json.dumps(QUESTIONS[p['questions'][0]][0])}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        c.check(es.send("GET", f"/_ingest/pipeline/{p['pipeline']}")[0] == 200, f"pipeline {p['pipeline']} exists")
        settings = index_settings(es, p["index"])
        if not c.check(settings is not None, f"index {p['index']} exists"):
            return
        c.equal(settings.get("index.default_pipeline"), p["pipeline"], "the pipeline is applied automatically")
        c.equal((field_mapping(es, p["index"], p["field"]) or {}).get("type"), "sparse_vector",
                f"{p['field']} is a sparse_vector field")
        es.send("POST", f"/{p['index']}/_refresh")
        hits = es.post(f"/{p['index']}/_search", {"size": 50, "_source": [p["field"]]})["hits"]["hits"]
        c.equal(sorted(h["_id"] for h in hits), sorted(a for a, _, _ in ARTICLES), "all articles are indexed")
        c.check(hits and all(h["_source"].get(p["field"]) for h in hits), f"every article has ELSER tokens in {p['field']}")
        for i in p["questions"]:
            question, want = QUESTIONS[i]
            status, response = es.send("POST", f"/{p['index']}/_search", json.dumps({"size": 1, "query": {
                "sparse_vector": {"field": p["field"], "inference_id": ELSER, "query": question}}}).encode(),
                "application/json", timeout=180)
            got = get(response, "hits.hits.0._id")
            c.check(status == 200 and got == want, f'a sparse_vector query for "{question}" finds the right article',
                    f"HTTP {status}, top hit {got!r}")
