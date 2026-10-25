import json
import time

from lib.tasklib import Task, get


class UpdateByQueryTask(Task):
    id = "ingest-update-by-query-task"
    title = "Update by query in the background: conflicts=proceed and the tasks API"
    covers = ["ingest.reindex.update-by-query-conflicts", "ingest.reindex.update-by-query",
              "ingest.reindex.tasks-api", "ingest.reindex.painless"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"tickets-{iid}", "docs": rnd.randint(300, 800), "status": rnd.choice(["open", "pending"]),
                "new_status": rnd.choice(["escalated", "archived"]), "batch": rnd.choice([50, 100])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        statuses = ["open", "pending", "closed"]
        bulk = "".join(json.dumps({"index": {}}) + "\n" +
                       json.dumps({"ticket": i, "status": statuses[i % 3], "priority": i % 5}) + "\n"
                       for i in range(p["docs"]))
        es.send("POST", f"/{p['index']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In the index `{p['index']}`, set `status` to "{p['new_status']}" for every ticket whose status is
"{p['status']}", with an update by query that:

  - runs in the background as a task (the request returns a task ID instead of waiting)
  - doesn't abort when it hits version conflicts (documents changed while it runs)
  - processes {p['batch']} documents per batch

Then look the task up with the tasks API to check that it completed.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST {p['index']}/_update_by_query?conflicts=proceed&wait_for_completion=false&scroll_size={p['batch']}&refresh=true
{{
  "query": {{ "term": {{ "status.keyword": "{p['status']}" }} }},
  "script": {{
    "source": "ctx._source.status = params.status",
    "params": {{ "status": "{p['new_status']}" }}
  }}
}}

# With the "task" value from the response:
# GET _tasks/<task id>
"""

    def stored_tasks(self, es, index):
        es.send("POST", "/.tasks/_refresh")
        status, response = es.send("POST", "/.tasks/_search?size=20", json.dumps({
            "query": {"bool": {"filter": [{"term": {"task.action": "indices:data/write/update/byquery"}},
                                          {"match_phrase": {"task.description": index}}]}}}).encode(),
            "application/json")
        return get(response, "hits.hits", []) if status == 200 else []

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        # A background task stores its result in .tasks when it completes; give it time to finish
        tasks = []
        for _ in range(30):
            tasks = self.stored_tasks(es, p["index"])
            running = es.get("/_tasks?actions=*byquery").get("nodes")
            if tasks and not running:
                break
            time.sleep(1)
        es.send("POST", f"/{p['index']}/_refresh")
        left = es.post(f"/{p['index']}/_count", {"query": {"term": {"status.keyword": p["status"]}}})["count"]
        c.equal(left, 0, f'no ticket has status "{p["status"]}" any more')
        expected = sum(1 for i in range(p["docs"]) if ["open", "pending", "closed"][i % 3] == p["status"])
        got = es.post(f"/{p['index']}/_count", {"query": {"term": {"status.keyword": p["new_status"]}}})["count"]
        c.equal(got, expected, f'{expected} tickets now have status "{p["new_status"]}"')
        if not c.check(tasks, "it ran in the background as a task (its result is stored in .tasks)"):
            return
        task = tasks[0]["_source"]
        c.check(task.get("completed"), "the task completed")
        batches = get(task, "response.batches", 0)
        want = -(-expected // p["batch"])   # documents / batch size, rounded up
        c.check(batches == want, f"it used batches of {p['batch']} documents",
                f"{expected} documents took {batches} batches; with {p['batch']} per batch it would be {want}")
        c.check(get(task, "task.status.version_conflicts") is not None and not get(task, "response.failures"),
                "it finished without failures")

    def cleanup(self, ctx):
        # The stored task results mention the index; remove them too
        ctx.es.send("POST", "/.tasks/_delete_by_query?refresh=true", json.dumps(
            {"query": {"match_phrase": {"task.description": ctx.p["index"]}}}).encode(), "application/json")
