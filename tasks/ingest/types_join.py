import json
import random

from lib.tasklib import Task, field_mapping, get
from tasks.ingest._common import send

TOPICS = ["shard sizing", "ILM rollover", "snapshot restore", "ingest pipelines", "cross-cluster search"]


def forum(seed):
    rnd = random.Random(seed)
    questions = [{"id": f"q{n}", "title": f"How to handle {t}?", "votes": rnd.randint(0, 30)}
                 for n, t in enumerate(rnd.sample(TOPICS, 4))]
    answers = []
    for n in range(7):
        q = rnd.choice(questions)
        answers.append({"id": f"a{n}", "parent": q["id"], "text": rnd.choice(["Use the API", "Check the docs",
                                                                              "Increase the heap"]),
                        "accepted": rnd.random() < 0.4})
    return questions, answers


class TypesJoin(Task):
    id = "ingest-types-join"
    title = "Parent-child documents with the join field type"
    covers = ["ingest.types.join", "ingest.methods.bulk", "ingest.mapping.meta.routing"]

    def params(self, rnd, iid):
        return {"index": f"forum-{iid}", "field": rnd.choice(["post_type", "qa_relation"]),
                "seed": rnd.randrange(10**6)}

    def prompt(self, ctx):
        p = ctx.p
        questions, answers = forum(p["seed"])
        lines = [f"  question {q['id']}: {json.dumps({k: v for k, v in q.items() if k != 'id'})}" for q in questions]
        lines += [f"  answer {a['id']} to {a['parent']}: "
                  f"{json.dumps({k: v for k, v in a.items() if k not in ('id', 'parent')})}" for a in answers]
        return f"""
Create the index `{p['index']}` for a Q&A forum where questions and answers are separate documents in
the same index, with a parent-child relation from question (parent) to answer (child) stored in
the join field `{p['field']}`. Map title and text as full text, votes as integer, accepted as boolean.

Index the following documents, using the ids shown as document _ids (q0, a3, ...), so that
has_child / has_parent queries work:

{chr(10).join(lines)}
"""

    def solution(self, ctx):
        p = ctx.p
        questions, answers = forum(p["seed"])
        lines = []
        for q in questions:
            lines.append(f'{{ "index": {{ "_id": "{q["id"]}" }} }}')
            lines.append(json.dumps({"title": q["title"], "votes": q["votes"], p["field"]: "question"}))
        for a in answers:
            lines.append(f'{{ "index": {{ "_id": "{a["id"]}", "routing": "{a["parent"]}" }} }}')
            lines.append(json.dumps({"text": a["text"], "accepted": a["accepted"],
                                     p["field"]: {"name": "answer", "parent": a["parent"]}}))
        nl = "\n"
        return f"""
PUT {p['index']}
{{
  "mappings": {{
    "properties": {{
      "title": {{ "type": "text" }},
      "text": {{ "type": "text" }},
      "votes": {{ "type": "integer" }},
      "accepted": {{ "type": "boolean" }},
      "{p['field']}": {{
        "type": "join",
        "relations": {{ "question": "answer" }}
      }}
    }}
  }}
}}

POST {p['index']}/_bulk?refresh=true
{nl.join(lines)}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = send(es, "HEAD", f"/{p['index']}")
        if not c.check(status == 200, f"index {p['index']} exists"):
            return
        m = field_mapping(es, p["index"], p["field"]) or {}
        c.check(m.get("type") == "join" and m.get("relations") == {"question": "answer"},
                f"{p['field']} is a join field with question -> answer", f"found {m}")
        questions, answers = forum(p["seed"])
        send(es, "POST", f"/{p['index']}/_refresh")

        def ids(query):
            status, response = send(es, "GET", f"/{p['index']}/_search", {"size": 50, "_source": False, "query": query})
            return sorted(h["_id"] for h in get(response, "hits.hits", [])) if status == 200 else f"error {status}"

        c.equal(ids({"match_all": {}}), sorted([q["id"] for q in questions] + [a["id"] for a in answers]),
                "all documents are indexed with the given ids")
        c.equal(ids({"has_child": {"type": "answer", "query": {"term": {"accepted": True}}}}),
                sorted({a["parent"] for a in answers if a["accepted"]}),
                "has_child finds the questions with an accepted answer")
        q = random.choice(questions)
        c.equal(ids({"parent_id": {"type": "answer", "id": q["id"]}}),
                sorted(a["id"] for a in answers if a["parent"] == q["id"]),
                f"parent_id finds the answers of {q['id']}")
        status, response = send(es, "GET", f"/{p['index']}/_search", {"size": 50, "query": {"has_parent": {
            "parent_type": "question", "query": {"match_all": {}}}}})
        routed = all(h.get("_routing") == next(a["parent"] for a in answers if a["id"] == h["_id"])
                     for h in get(response, "hits.hits", []) if h["_id"].startswith("a"))
        c.check(routed and len(get(response, "hits.hits", [])) == len(answers),
                "answers are routed to the shard of their question")
