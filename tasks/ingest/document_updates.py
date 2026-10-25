import random

from lib.tasklib import Task, get
from tasks.ingest._common import bulk, send


def accounts(seed):
    rnd = random.Random(seed)
    return {f"acc-{n}": {"owner": o, "balance": rnd.randint(10, 500), "tags": rnd.sample(["vip", "new", "eu"], 1),
                         "email": f"{o}@example.com"}
            for n, o in enumerate(["ines", "jon", "kai", "lia"], 1)}


class DocumentUpdates(Task):
    id = "ingest-document-updates"
    title = "Document APIs: scripted updates, upserts, partial updates, deletes and multi-get"
    covers = ["ingest.methods.document-apis", "ingest.reindex.painless"]

    def params(self, rnd, iid):
        return {"index": f"accounts-{iid}", "seed": rnd.randrange(10**6), "amount": rnd.randint(5, 95),
                "tag": rnd.choice(["vip", "eu", "audited"]), "new": f"acc-{rnd.randint(10, 99)}",
                "visits": rnd.randint(2, 5), "email": f"kai.{rnd.randint(1, 99)}@example.org"}

    def setup(self, ctx):
        docs = accounts(ctx.p["seed"])
        bulk(ctx.es, ctx.p["index"], list(docs.values()), ids=list(docs))

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The index `{p['index']}` holds accounts acc-1 to acc-4 ({{"owner", "balance", "tags", "email"}}).
Use the document APIs (not update by query) to:

  1. acc-1: with ONE update request and a script that takes its values as parameters, add
     {p['amount']} to balance and add the tag "{p['tag']}" to tags unless it is already there
  2. {p['new']} (doesn't exist yet): write ONE update request that, when the document doesn't
     exist, creates it as {{ "owner": "max", "balance": 0, "visits": 1 }}, and when it exists,
     increments visits by 1. Send it {p['visits']} times, so visits ends at {p['visits']}.
  3. acc-3: change only the email to "{p['email']}" with a partial update
  4. delete acc-4
  5. fetch acc-1, acc-3 and {p['new']} in one request to check the result
"""

    def solution(self, ctx):
        p = ctx.p
        upsert = f"""
POST {p['index']}/_update/{p['new']}
{{
  "script": {{ "source": "ctx._source.visits += 1" }},
  "upsert": {{ "owner": "max", "balance": 0, "visits": 1 }}
}}
"""
        return f"""
POST {p['index']}/_update/acc-1
{{
  "script": {{
    "source": "ctx._source.balance += params.amount; if (!ctx._source.tags.contains(params.tag)) {{ ctx._source.tags.add(params.tag) }}",
    "params": {{ "amount": {p['amount']}, "tag": "{p['tag']}" }}
  }}
}}
{upsert * p['visits']}
POST {p['index']}/_update/acc-3
{{
  "doc": {{ "email": "{p['email']}" }}
}}

DELETE {p['index']}/_doc/acc-4

GET {p['index']}/_mget
{{
  "ids": ["acc-1", "acc-3", "{p['new']}"]
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        docs = accounts(p["seed"])
        status, response = send(es, "POST", f"/{p['index']}/_mget",
                                {"ids": ["acc-1", "acc-2", "acc-3", "acc-4", p["new"]]})
        got = {d["_id"]: d.get("_source") if d.get("found") else None for d in get(response, "docs", [])}
        a1 = got.get("acc-1") or {}
        tags = docs["acc-1"]["tags"] + ([] if p["tag"] in docs["acc-1"]["tags"] else [p["tag"]])
        c.equal(a1.get("balance"), docs["acc-1"]["balance"] + p["amount"], f"acc-1's balance grew by {p['amount']}")
        c.equal(sorted(a1.get("tags", [])), sorted(tags), f"acc-1 has the tag {p['tag']} exactly once")
        c.equal(got.get(p["new"]), {"owner": "max", "balance": 0, "visits": p["visits"]},
                f"{p['new']} was created by the upsert and has visits {p['visits']}")
        c.equal(got.get("acc-3"), dict(docs["acc-3"], email=p["email"]), "acc-3 has only the new email changed")
        c.equal(got.get("acc-4", "?"), None, "acc-4 was deleted")
        c.equal(got.get("acc-2"), docs["acc-2"], "acc-2 is unchanged")
