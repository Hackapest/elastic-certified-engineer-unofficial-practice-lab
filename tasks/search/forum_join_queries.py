import json
import random

from lib.tasklib import Task

TAGS = ["elasticsearch", "kibana", "logstash", "beats", "security", "ingest"]
USERS = ["ana", "bo", "chen", "dara", "eli", "femi", "gus", "hana"]


class ForumJoinQueries(Task):
    id = "search-forum-join-queries"
    title = "Parent/child search on a join field (has_child, has_parent)"
    covers = ["search.joining.has-child", "search.joining.has-parent", "search.compound.bool"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        return {"index": f"forum-{iid}", "seed": rnd.randrange(10**6), "kind": rnd.choice(["has_child", "has_parent"]),
                "tag": rnd.choice(TAGS), "user": rnd.choice(USERS), "min_answers": rnd.choice([2, 3]),
                "min_votes": rnd.choice([3, 5])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        rnd = random.Random(p["seed"])
        es.put(f"/{p['index']}", {"mappings": {"properties": {
            "qa": {"type": "join", "relations": {"question": "answer"}},
            "title": {"type": "text"}, "body": {"type": "text"}, "tags": {"type": "keyword"},
            "user": {"type": "keyword"}, "votes": {"type": "integer"}}}})
        lines = []
        for q in range(60):
            qid = f"q{q}"
            lines.append(json.dumps({"index": {"_id": qid}}))
            lines.append(json.dumps({"qa": "question", "title": f"Question {q}", "tags": rnd.sample(TAGS, 2),
                                     "user": rnd.choice(USERS), "votes": rnd.randrange(0, 10)}))
            for a in range(rnd.randrange(0, 6)):
                lines.append(json.dumps({"index": {"_id": f"{qid}-a{a}", "routing": qid}}))
                lines.append(json.dumps({"qa": {"name": "answer", "parent": qid}, "body": f"Answer {a} to {qid}",
                                         "user": rnd.choice(USERS), "votes": rnd.randrange(0, 10)}))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", ("\n".join(lines) + "\n").encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        if p["kind"] == "has_child":
            want = f"""the QUESTIONS tagged "{p['tag']}" (tags) that have at least {p['min_answers']} answers with
at least {p['min_votes']} votes (votes) each."""
        else:
            want = f"""the ANSWERS written by "{p['user']}" (user) to questions tagged "{p['tag']}" (tags). Answers
don't have tags: the tag is on the question."""
        return f"""
The index `{p['index']}` holds forum questions and their answers, linked by the join field qa
(relation question -> answer; look at the mapping). Find {want}

Return all of them in one response.
"""

    def solution(self, ctx):
        p = ctx.p
        if p["kind"] == "has_child":
            query = f"""{{
    "bool": {{
      "filter": [
        {{ "term": {{ "tags": "{p['tag']}" }} }},
        {{ "has_child": {{
            "type": "answer",
            "min_children": {p['min_answers']},
            "query": {{ "range": {{ "votes": {{ "gte": {p['min_votes']} }} }} }}
        }} }}
      ]
    }}
  }}"""
        else:
            query = f"""{{
    "bool": {{
      "filter": [
        {{ "term": {{ "user": "{p['user']}" }} }},
        {{ "has_parent": {{ "parent_type": "question", "query": {{ "term": {{ "tags": "{p['tag']}" }} }} }} }}
      ]
    }}
  }}"""
        return f"""
GET {p['index']}/_search
{{
  "size": 1000,
  "query": {query}
}}
"""

    def wrong_answer(self, ctx):
        p = ctx.p
        if p["kind"] == "has_child":   # any number of such answers
            return self.solution(ctx).replace(f'"min_children": {p["min_answers"]},', "")
        # The user's answers anywhere, and questions by the user
        return self.solution(ctx).replace(
            f'{{ "has_parent": {{ "parent_type": "question", "query": {{ "term": {{ "tags": "{p["tag"]}" }} }} }} }}',
            '{ "exists": { "field": "user" } }')
