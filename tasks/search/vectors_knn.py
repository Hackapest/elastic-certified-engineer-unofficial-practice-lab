import json

from lib.tasklib import Task
from tasks.search._vectors import CATEGORIES, create_articles, vector


class VectorsKnn(Task):
    id = "search-vectors-knn"
    title = "Approximate kNN search on a dense_vector field, with a filter"
    covers = ["search.semantic.knn-query", "search.semantic.knn-option", "ingest.types.dense-vector"]
    answer = "query"
    compare = "hits_scored"

    def params(self, rnd, iid):
        return {"index": f"articles-vec-{iid}", "seed": rnd.randrange(2**31), "query": vector(rnd),
                "category": rnd.choice(CATEGORIES), "k": rnd.choice([5, 10]), "candidates": rnd.choice([50, 100])}

    def setup(self, ctx):
        create_articles(ctx.es, ctx.p["index"], ctx.p["seed"])

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds articles with an 8-dimensional embedding in the dense_vector field
`embedding` (look at its mapping). Find the {p['k']} articles in the category "{p['category']}" whose
embeddings are closest to this query vector:

  {json.dumps(p['query'])}

Use approximate kNN with {p['candidates']} candidates per shard. The category condition must be applied
during the kNN search (not afterwards), so you get {p['k']} results from that category. Return them
best first.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {p['index']}/_search
{{
  "size": {p['k']},
  "knn": {{
    "field": "embedding",
    "query_vector": {json.dumps(p['query'])},
    "k": {p['k']},
    "num_candidates": {p['candidates']},
    "filter": {{ "term": {{ "category": "{p['category']}" }} }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Filters after the kNN search instead of during it
        p = ctx.p
        return f"""
GET {p['index']}/_search
{{
  "size": {p['k']},
  "knn": {{
    "field": "embedding",
    "query_vector": {json.dumps(p['query'])},
    "k": {p['k']},
    "num_candidates": {p['candidates']}
  }},
  "post_filter": {{ "term": {{ "category": "{p['category']}" }} }}
}}
"""
