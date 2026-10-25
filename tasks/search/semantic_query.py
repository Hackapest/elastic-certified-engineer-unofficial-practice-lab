import json

from lib.tasklib import Task, get, same_hits
from tasks.search._knowledge_base import ARTICLES, QUESTIONS


class SemanticQuery(Task):
    id = "search-semantic-query"
    title = "Query a semantic_text field, alone and combined with a filter"
    covers = ["search.semantic.semantic-query", "search.semantic.semantic-text", "search.compound.bool"]
    answer = "query"
    requires = ("ml",)

    def params(self, rnd, iid):
        question = rnd.randrange(len(QUESTIONS))
        excluded = rnd.choice([a for a, _, _ in ARTICLES if a != QUESTIONS[question][1]])
        return {"index": f"kb-{iid}", "question": question, "excluded": excluded, "size": rnd.choice([2, 3])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"mappings": {"properties": {
            "title": {"type": "text"}, "topic": {"type": "keyword"},
            "body": {"type": "semantic_text", "inference_id": ".elser-2-elasticsearch"}}}})
        bulk = "".join(json.dumps({"index": {"_id": a}}) + "\n" + json.dumps({"title": t, "topic": a, "body": b}) + "\n"
                       for a, t, b in ARTICLES)
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson", timeout=300)

    def prompt(self, ctx):
        p = ctx.p
        question = QUESTIONS[p["question"]][0]
        return f"""
The index `{p['index']}` holds help center articles; `body` is a semantic_text field (look at the
mapping). A customer asks:

  "{question}"

Return the {p['size']} articles that match the question best by meaning, best first, but never the
article whose topic (keyword) is "{p['excluded']}". (If ELSER isn't running yet: ./ece ml-setup)
"""

    def solution(self, ctx):
        p = ctx.p
        question = QUESTIONS[p["question"]][0]
        return f"""
GET {p['index']}/_search
{{
  "size": {p['size']},
  "query": {{
    "bool": {{
      "must": {{
        "semantic": {{ "field": "body", "query": {json.dumps(question)} }}
      }},
      "must_not": {{ "term": {{ "topic": "{p['excluded']}" }} }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Plain keyword matching on the title instead of meaning
        p = ctx.p
        question = QUESTIONS[p["question"]][0]
        return f"""
GET {p['index']}/_search
{{
  "size": {p['size']},
  "query": {{
    "bool": {{
      "must": {{ "match": {{ "title": {json.dumps(question)} }} }},
      "must_not": {{ "term": {{ "topic": "{p['excluded']}" }} }}
    }}
  }}
}}
"""

    def grade(self, ctx, c, answer, reference):
        same_hits(c, answer, reference, ordered=True)
        ids = [h["_id"] for h in get(answer, "hits.hits", [])]
        c.check(ctx.p["excluded"] not in ids, f'the article "{ctx.p["excluded"]}" is never returned')
