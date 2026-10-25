import json

from lib.tasklib import Task, field_mapping, get
from tasks.search._knowledge_base import ARTICLES, QUESTIONS


class SemanticTextIndex(Task):
    id = "search-semantic-text-index"
    title = "Set up semantic search with a semantic_text field"
    covers = ["search.semantic.semantic-text", "search.semantic.semantic-query", "ingest.types.semantic-text",
              "search.semantic.inference-endpoint"]
    answer = "state"
    requires = ("ml",)

    def params(self, rnd, iid):
        return {"index": f"helpcenter-{iid}", "field": rnd.choice(["body_semantic", "content", "semantic_body"]),
                "questions": rnd.sample(range(len(QUESTIONS)), 3)}

    def prompt(self, ctx):
        p = ctx.p
        docs = "\n".join(f"  {json.dumps({'id': a, 'title': t, 'body': b})}" for a, t, b in ARTICLES)
        return f"""
Make the help center articles searchable by meaning. Create the index `{p['index']}` with:

  title    text
  body     text, which is also copied into a semantic_text field `{p['field']}`
           that uses the built-in ELSER inference endpoint (.elser-2-elasticsearch)

and index these {len(ARTICLES)} articles (use the "id" as the document _id):

{docs}

Test it with a semantic query on `{p['field']}`, e.g. "{QUESTIONS[p['questions'][0]][0]}".
(If ELSER isn't running yet: ./ece ml-setup)
"""

    def solution(self, ctx):
        p = ctx.p
        bulk = "\n".join(json.dumps({"index": {"_id": a}}) + "\n" + json.dumps({"title": t, "body": b})
                         for a, t, b in ARTICLES)
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "properties": {{
      "title": {{ "type": "text" }},
      "body": {{ "type": "text", "copy_to": "{p['field']}" }},
      "{p['field']}": {{ "type": "semantic_text", "inference_id": ".elser-2-elasticsearch" }}
    }}
  }}
}}

POST {p['index']}/_bulk?refresh=true
{bulk}

GET {p['index']}/_search
{{
  "query": {{
    "semantic": {{ "field": "{p['field']}", "query": "{QUESTIONS[p['questions'][0]][0]}" }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        mapping = field_mapping(es, p["index"], p["field"])
        if not c.check(mapping is not None, f"index {p['index']} has the field {p['field']}"):
            return
        c.equal(mapping.get("type"), "semantic_text", f"{p['field']} is a semantic_text field")
        c.check(mapping.get("inference_id") in (None, ".elser-2-elasticsearch"), "it uses the ELSER endpoint",
                f"inference_id is {mapping.get('inference_id')}")
        body = field_mapping(es, p["index"], "body") or {}
        c.check(p["field"] in (body.get("copy_to") or []) or body.get("type") == "semantic_text",
                f"body is copied into {p['field']}", f"body mapping: {body}")
        es.send("POST", f"/{p['index']}/_refresh")
        ids = {h["_id"] for h in es.post(f"/{p['index']}/_search", {"size": 50, "_source": False})["hits"]["hits"]}
        c.equal(ids, {a for a, _, _ in ARTICLES}, "all articles are indexed with their ids")
        for i in p["questions"]:
            question, want = QUESTIONS[i]
            status, response = es.send("POST", f"/{p['index']}/_search", json.dumps(
                {"size": 1, "query": {"semantic": {"field": p["field"], "query": question}}}).encode(),
                "application/json", timeout=180)
            got = get(response, "hits.hits.0._id")
            c.check(status == 200 and got == want, f'a semantic query for "{question}" finds the right article',
                    f"HTTP {status}, top hit {got!r}, expected {want!r}")
