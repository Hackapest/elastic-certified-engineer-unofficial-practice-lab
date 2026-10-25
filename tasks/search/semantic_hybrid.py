import json

from lib.tasklib import Task
from tasks.search._knowledge_base import ARTICLES, QUESTIONS


class SemanticHybrid(Task):
    id = "search-semantic-hybrid"
    title = "Hybrid search: semantic_text and full-text combined with RRF"
    covers = ["search.semantic.hybrid", "search.semantic.semantic-query", "search.semantic.retriever.rrf",
              "search.semantic.retriever.standard"]
    answer = "query"
    compare = "hits_ordered"
    requires = ("ml",)

    def params(self, rnd, iid):
        return {"index": f"kb-hybrid-{iid}", "question": rnd.randrange(len(QUESTIONS)), "size": rnd.choice([3, 4])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"mappings": {"properties": {
            "title": {"type": "text"},
            "body": {"type": "text", "copy_to": "body_semantic"},
            "body_semantic": {"type": "semantic_text", "inference_id": ".elser-2-elasticsearch"}}}})
        bulk = "".join(json.dumps({"index": {"_id": a}}) + "\n" + json.dumps({"title": t, "body": b}) + "\n"
                       for a, t, b in ARTICLES)
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson", timeout=300)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` has help center articles with `title` and `body` (text) and `body_semantic`
(semantic_text, a copy of body). For the question

  "{QUESTIONS[p['question']][0]}"

run a hybrid search that combines a semantic query on body_semantic with a full-text match on
title and body (multi_match), merged with reciprocal rank fusion (default settings). Return the
top {p['size']} articles. (If ELSER isn't running yet: ./ece ml-setup)
"""

    def solution(self, ctx):
        p = ctx.p
        question = json.dumps(QUESTIONS[p["question"]][0])
        return f"""
GET {p['index']}/_search
{{
  "size": {p['size']},
  "retriever": {{
    "rrf": {{
      "retrievers": [
        {{
          "standard": {{
            "query": {{ "semantic": {{ "field": "body_semantic", "query": {question} }} }}
          }}
        }},
        {{
          "standard": {{
            "query": {{ "multi_match": {{ "query": {question}, "fields": ["title", "body"] }} }}
          }}
        }}
      ]
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Only the full-text part
        p = ctx.p
        question = json.dumps(QUESTIONS[p["question"]][0])
        return f"""
GET {p['index']}/_search
{{
  "size": {p['size']},
  "query": {{ "multi_match": {{ "query": {question}, "fields": ["title", "body"] }} }}
}}
"""
