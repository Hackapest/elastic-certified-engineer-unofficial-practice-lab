import json

from lib.tasklib import Task, get

HEADERS = {"elastic-api-version": "2023-10-31"}


def kibana(ctx):
    k = ctx.kibana()
    k.headers.update(HEADERS)
    return k


class WiredStreams(Task):
    id = "ingest-wired-streams"
    title = "Exam-style: route logs into a wired child stream with its own mapping and retention"
    covers = ["ingest.streams.wired-enable", "ingest.streams.partition", "ingest.streams.map-fields",
              "ingest.streams.retention", "ingest.streams.data-quality", "ingest.streams.api"]
    size = "exam"
    answer = "state"
    requires = ("kibana",)

    def params(self, rnd, iid):
        team = rnd.choice(["checkout", "payments", "search"])
        return {"child": f"logs.{team}-{iid}", "service": f"{team}-service-{iid}",
                "retention": rnd.choice(["7d", "14d", "30d"]), "failure_retention": rnd.choice(["3d", "5d"]),
                "amount_type": "double"}   # wired streams only allow a few field types (no float)

    def setup(self, ctx):
        status, _ = kibana(ctx).send("GET", "/api/streams/logs")
        ctx.p["was_enabled"] = status == 200

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Use wired streams in Kibana A (Streams in the Kibana menu; the Streams API via `kbn:/api/streams`
in Dev Tools works too):

  1. Enable wired streams if they aren't yet, so that the root stream `logs` exists.
  2. Route all logs of the service "{p['service']}" (resource.attributes.service.name) from `logs` into
     a new child stream `{p['child']}`.
  3. In `{p['child']}`, map attributes.order_id as keyword and attributes.amount as {p['amount_type']}.
  4. Keep the data of `{p['child']}` for {p['retention']}, and its failed documents (failure store) for {p['failure_retention']}.

Then send a test document to `logs`, e.g.
  POST logs/_doc
  {{ "@timestamp": "2026-10-25T10:00:00Z", "service.name": "{p['service']}", "order_id": "A-1", "amount": 9.5 }}
and check that it arrives in `{p['child']}` (wired streams move non-standard fields under attributes.*).
"""

    def body(self, p):
        return {"ingest": {"lifecycle": {"dsl": {"data_retention": p["retention"]}}, "processing": {"steps": []},
                           "settings": {},
                           "failure_store": {"lifecycle": {"enabled": {"data_retention": p["failure_retention"]}}},
                           "wired": {"routing": [], "fields": {"attributes.order_id": {"type": "keyword"},
                                                               "attributes.amount": {"type": p["amount_type"]}}}}}

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST kbn:/api/streams/_enable

POST kbn:/api/streams/logs/_fork
{{
  "stream": {{ "name": "{p['child']}" }},
  "where": {{ "field": "resource.attributes.service.name", "eq": "{p['service']}" }}
}}

PUT kbn:/api/streams/{p['child']}/_ingest
{json.dumps(self.body(p), indent=2)}

POST logs/_doc?refresh=true
{{ "@timestamp": "2026-10-25T10:00:00Z", "service.name": "{p['service']}", "order_id": "A-1", "amount": 9.5 }}
"""

    def apply_solution(self, ctx):
        p, k = ctx.p, kibana(ctx)
        for method, path, body in (
                ("POST", "/api/streams/_enable", None),
                ("POST", "/api/streams/logs/_fork",
                 {"stream": {"name": p["child"]}, "where": {"field": "resource.attributes.service.name",
                                                            "eq": p["service"]}}),
                ("PUT", f"/api/streams/{p['child']}/_ingest", self.body(p))):
            status, response = k.send(method, path, json.dumps(body).encode() if body else None, "application/json")
            if status != 200:
                return f"{method} {path}: HTTP {status}: {str(response)[:300]}"
        return None

    def verify(self, ctx, c):
        p, es, k = ctx.p, ctx.es, kibana(ctx)
        status, root = k.send("GET", "/api/streams/logs")
        if not c.check(status == 200, "wired streams are enabled (the root stream logs exists)"):
            return
        routing = get(root, "stream.ingest.wired.routing", [])
        rule = next((r for r in routing if r.get("destination") == p["child"]), None)
        c.check(rule, f"logs routes into {p['child']}", f"routing of logs: {routing}")
        status, child = k.send("GET", f"/api/streams/{p['child']}")
        if not c.check(status == 200, f"the stream {p['child']} exists"):
            return
        ingest = get(child, "stream.ingest", {})
        fields = get(ingest, "wired.fields", {})
        c.equal({f: get(fields, f"{f}.type", (fields.get(f) or {}).get("type")) for f in ("attributes.order_id", "attributes.amount")},
                {"attributes.order_id": "keyword", "attributes.amount": p["amount_type"]}, "the fields are mapped")
        c.equal(get(ingest, "lifecycle.dsl.data_retention"), p["retention"], f"data is kept for {p['retention']}")
        c.equal(get(ingest, "failure_store.lifecycle.enabled.data_retention"), p["failure_retention"],
                f"failed documents are kept for {p['failure_retention']}")
        doc = {"@timestamp": "2026-10-25T11:00:00Z", "service.name": p["service"], "order_id": "verify-1",
               "amount": 1.5}
        status, response = es.send("POST", "/logs/_doc?refresh=true", json.dumps(doc).encode(), "application/json")
        index = (response or {}).get("_index", "")
        c.check(status in (200, 201) and p["child"] in index, f"a log of {p['service']} is routed into {p['child']}",
                f"it went to {index or response}")
        if status in (200, 201):
            es.send("DELETE", f"/{index}/_doc/{response['_id']}?refresh=true")

    def cleanup(self, ctx):
        k = kibana(ctx)
        k.send("DELETE", f"/api/streams/{ctx.p['child']}")
        if not ctx.p.get("was_enabled", True):
            k.send("POST", "/api/streams/_disable")
