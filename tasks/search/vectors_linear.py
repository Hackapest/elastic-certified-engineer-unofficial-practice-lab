import json

from lib.tasklib import Task
from tasks.search._vectors import WORDS, create_articles, vector


class VectorsLinear(Task):
    id = "search-vectors-linear"
    title = "Weighted hybrid search with the linear retriever"
    covers = ["search.semantic.retriever.linear", "search.semantic.retriever.standard",
              "search.semantic.retriever.knn"]
    answer = "query"
    compare = "hits_scored"

    def params(self, rnd, iid):
        return {"index": f"articles-linear-{iid}", "seed": rnd.randrange(2**31), "query": vector(rnd),
                "text": " ".join(rnd.sample(WORDS, 2)), "text_weight": rnd.choice([0.3, 0.5, 2.0]),
                "size": rnd.choice([5, 10])}

    def setup(self, ctx):
        create_articles(ctx.es, ctx.p["index"], ctx.p["seed"])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds articles with a text field `title` and an 8-dimensional dense_vector
field `embedding`. Run a hybrid search that adds up the scores of:

  - a full-text match on title for "{p['text']}", weighted {p['text_weight']}
  - an approximate kNN search on embedding (k = 50, 100 candidates) for this vector, weighted 1:
    {json.dumps(p['query'])}

Both scores must be normalized to the range 0-1 (min-max) before they're weighted and added.
Return the top {p['size']} documents.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {p['index']}/_search
{{
  "size": {p['size']},
  "retriever": {{
    "linear": {{
      "retrievers": [
        {{
          "retriever": {{ "standard": {{ "query": {{ "match": {{ "title": "{p['text']}" }} }} }} }},
          "weight": {p['text_weight']},
          "normalizer": "minmax"
        }},
        {{
          "retriever": {{
            "knn": {{
              "field": "embedding",
              "query_vector": {json.dumps(p['query'])},
              "k": 50,
              "num_candidates": 100
            }}
          }},
          "weight": 1,
          "normalizer": "minmax"
        }}
      ],
      "rank_window_size": 50
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Without normalization
        return self.solution(ctx).replace(',\n          "normalizer": "minmax"', "")
