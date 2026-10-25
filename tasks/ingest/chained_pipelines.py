import random

from lib.tasklib import Task, get
from tasks.ingest._common import check_against_reference, field, render_pipeline, send

APPS = ["web", "db", "batch"]


def event(rnd):
    app = rnd.choice(APPS)
    doc = {"app": app, "level": rnd.choice(["info", "warn", "error"])}
    if app == "db":
        doc["query_ms"] = str(rnd.randint(1, 5000))
    if app == "web":
        doc["path"] = rnd.choice(["/", "/cart", "/api/items"])
    return doc


class ChainedPipelines(Task):
    id = "ingest-chained-pipelines"
    title = "Chain pipelines with the pipeline processor and reroute documents (pipeline, reroute, metadata)"
    covers = ["ingest.pipelines.processor.pipeline", "ingest.pipelines.processor.reroute",
              "ingest.pipelines.metadata-access", "ingest.pipelines.conditionals",
              "ingest.pipelines.processor.set", "ingest.pipelines.processor.convert"]

    def params(self, rnd, iid):
        return {"common": f"evt-common-{iid}", "web": f"evt-web-{iid}", "db": f"evt-db-{iid}",
                "router": f"evt-router-{iid}", "errors": f"evt-errors-{iid}", "incoming": f"evt-incoming-{iid}",
                "web_team": rnd.choice(["frontend", "web-ops"]), "db_team": rnd.choice(["dba", "data-platform"])}

    def parts(self, p):
        common = [{"set": {"field": "event.original_index", "value": "{{{_index}}}"}},
                  {"set": {"field": "event.ingested", "value": "{{{_ingest.timestamp}}}"}}]
        web = [{"set": {"field": "team", "value": p["web_team"]}}]
        db = [{"set": {"field": "team", "value": p["db_team"]}},
              {"convert": {"field": "query_ms", "type": "long"}}]
        return common, web, db

    def reference(self, p):
        common, web, db = self.parts(p)
        cond = lambda procs, app: [{k: dict(v, **{"if": f"ctx.app == '{app}'"})} for x in procs for k, v in x.items()]
        return common + cond(web, "web") + cond(db, "db") + [
            {"reroute": {"if": "ctx.level == 'error'", "destination": p["errors"]}}]

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Events from several applications are indexed into `{p['incoming']}`, for example
{{ "app": "db", "level": "warn", "query_ms": "1532" }}. Build these ingest pipelines:

  {p['common']}   sets event.original_index to the name of the index the document was sent to,
                     and event.ingested to the time the document was ingested
  {p['web']}      sets team to "{p['web_team']}"
  {p['db']}       sets team to "{p['db_team']}" and converts query_ms to a long

and a pipeline `{p['router']}` that always runs `{p['common']}`, then runs `{p['web']}` for
documents whose app is "web" and `{p['db']}` for those whose app is "db" (other apps get neither),
and finally sends documents whose level is "error" to the index `{p['errors']}` with the reroute
processor. `{p['router']}` must call the other pipelines rather than copy their processors.
"""

    def solution(self, ctx):
        p = ctx.p
        common, web, db = self.parts(p)
        router = [{"pipeline": {"name": p["common"]}},
                  {"pipeline": {"name": p["web"], "if": "ctx.app == 'web'"}},
                  {"pipeline": {"name": p["db"], "if": "ctx.app == 'db'"}},
                  {"reroute": {"if": "ctx.level == 'error'", "destination": p["errors"]}}]
        return "\n".join(render_pipeline(n, procs) for n, procs in
                         ((p["common"], common), (p["web"], web), (p["db"], db), (p["router"], router)))

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        for name in ("common", "web", "db"):
            status, _ = send(es, "GET", f"/_ingest/pipeline/{p[name]}")
            c.check(status == 200, f"pipeline {p[name]} exists")
        status, response = send(es, "GET", f"/_ingest/pipeline/{p['router']}")
        if status == 200:
            called = {get(proc, "pipeline.name") for proc in get(response, f"{p['router']}.processors", [])}
            c.check({p["common"], p["web"], p["db"]} <= called,
                    f"{p['router']} calls the other pipelines with pipeline processors",
                    f"it calls: {sorted(x for x in called if x) or 'no pipeline'}")
        rnd = random.Random()
        docs = [{"_index": p["incoming"], "_source": event(rnd)} for _ in range(12)]
        docs[0]["_source"] = {"app": "web", "level": "error", "path": "/"}
        docs[1]["_source"] = {"app": "batch", "level": "info"}
        checks = [("documents end up in the right index", lambda r: r["index"]),
                  ("event.original_index is set", "event.original_index"),
                  ("event.ingested holds the ingest time",
                   lambda r: str(field(r["source"], "event.ingested"))[:2] == "20"
                   and "T" in str(field(r["source"], "event.ingested"))),
                  ("team is set per app", "team"),
                  ("query_ms is converted for db events", "query_ms")]
        check_against_reference(c, es, p["router"], self.reference(p), docs, checks)
