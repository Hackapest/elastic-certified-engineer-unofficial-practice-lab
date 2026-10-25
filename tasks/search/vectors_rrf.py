import json

from lib.tasklib import Task
from tasks.search._vectors import WORDS, create_articles, vector


class VectorsRrf(Task):
    id = "search-vectors-rrf"
    title = "Hybrid search: combine full-text and kNN with reciprocal rank fusion"
    covers = ["search.semantic.retriever.rrf", "search.semantic.retriever.standard",
              "search.semantic.retriever.knn", "search.fulltext.match"]
    answer = "query"
    compare = "hits_ordered"

    def params(self, rnd, iid):
        return {"index": f"articles-hybrid-{iid}", "seed": rnd.randrange(2**31), "query": vector(rnd),
                "text": " ".join(rnd.sample(WORDS, 2)), "window": rnd.choice([20, 50]),
                "constant": rnd.choice([20, 60]), "size": rnd.choice([5, 10])}

    def setup(self, ctx):
        create_articles(ctx.es, ctx.p["index"], ctx.p["seed"])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds articles with a text field `title` and an 8-dimensional
dense_vector field `embedding`. Run a hybrid search that combines:

  - a full-text match on title for "{p['text']}"
  - an approximate kNN search on embedding for this vector, k = {p['window']}, 100 candidates:
    {json.dumps(p['query'])}

Merge both result lists with reciprocal rank fusion, using a rank window of {p['window']} and a rank
constant of {p['constant']}. Return the top {p['size']} documents.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {p['index']}/_search
{{
  "size": {p['size']},
  "retriever": {{
    "rrf": {{
      "retrievers": [
        {{
          "standard": {{
            "query": {{ "match": {{ "title": "{p['text']}" }} }}
          }}
        }},
        {{
          "knn": {{
            "field": "embedding",
            "query_vector": {json.dumps(p['query'])},
            "k": {p['window']},
            "num_candidates": 100
          }}
        }}
      ],
      "rank_window_size": {p['window']},
      "rank_constant": {p['constant']}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Only the kNN part
        p = ctx.p
        return f"""
GET {p['index']}/_search
{{
  "size": {p['size']},
  "knn": {{
    "field": "embedding",
    "query_vector": {json.dumps(p['query'])},
    "k": {p['window']},
    "num_candidates": 100
  }}
}}
"""
