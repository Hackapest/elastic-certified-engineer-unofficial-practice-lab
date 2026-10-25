import json

from lib.tasklib import Task, get

LEVELS = ["INFO", "WARN", "ERROR"]


class LogsdbFailureStore(Task):
    id = "data-logsdb-failure-store"
    title = "A logsdb data stream with a failure store, and a failure store on an existing stream"
    covers = ["data.templates.logsdb", "data.templates.failure-store", "data.index.index-modes",
              "data.templates.data-stream-template", "data.templates.use-data-stream"]
    answer = "state"

    def params(self, rnd, iid):
        good = [{"@timestamp": f"2026-10-2{d}T{h:02d}:15:00Z", "service": rnd.choice(["cart", "auth", "search"]),
                 "level": rnd.choice(LEVELS), "message": f"request {d}{h} handled"}
                for d, h in ((1, 8), (1, 9), (2, 14), (3, 7), (3, 22))[:rnd.randint(3, 5)]]
        bad = [{"service": "cart", "level": "ERROR", "message": "no timestamp at all"},
               {"@timestamp": rnd.choice(["21/10/2026 10:00", "yesterday", "2026-13-45"]), "service": "auth",
                "level": "WARN", "message": "timestamp in the wrong format"}]
        docs = good + bad
        rnd.shuffle(docs)
        return {"template": f"applogs-{iid}", "stream": f"applogs-{iid}-prod", "audit": f"auditlogs-{iid}",
                "docs": docs, "good": len(good), "bad": len(bad)}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/_index_template/{p['audit']}", {"index_patterns": [p["audit"]], "data_stream": {}, "priority": 500})
        es.put(f"/_data_stream/{p['audit']}")
        es.post(f"/{p['audit']}/_doc?refresh=true", {"@timestamp": "2026-10-20T10:00:00Z", "event": "login"})

    def prompt(self, ctx):
        p = ctx.p
        docs = "\n".join(f"  {json.dumps(d)}" for d in p["docs"])
        return f"""
Application logs go to data streams named "applogs-{ctx.iid}-<environment>".

  1. Create the index template `{p['template']}` for these data streams. Their backing indices must
     use the logsdb index mode, and documents that can't be indexed (for example because of a
     missing or invalid @timestamp) must be kept in the data stream's failure store instead of
     being rejected. Map service and level as keyword, message as text.
  2. Index these documents into `{p['stream']}`, once (each line is one document):
{docs}
  3. The existing data stream `{p['audit']}` must also keep failed documents in its failure store
     from now on. Change only this data stream, not its index template.
"""

    def solution(self, ctx):
        p = ctx.p
        bulk = "\n".join('{ "create": {} }\n' + json.dumps(d) for d in p["docs"])
        return f"""
PUT _index_template/{p['template']}
{{
  "index_patterns": ["applogs-{ctx.iid}-*"],
  "data_stream": {{}},
  "priority": 500,
  "template": {{
    "settings": {{ "index.mode": "logsdb" }},
    "mappings": {{
      "properties": {{
        "service": {{ "type": "keyword" }},
        "level": {{ "type": "keyword" }},
        "message": {{ "type": "text" }}
      }}
    }},
    "data_stream_options": {{
      "failure_store": {{ "enabled": true }}
    }}
  }}
}}

POST {p['stream']}/_bulk?refresh=true
{bulk}

PUT _data_stream/{p['audit']}/_options
{{
  "failure_store": {{ "enabled": true }}
}}

GET {p['stream']}::failures/_search
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        sim = es.send("POST", f"/_index_template/_simulate_index/applogs-{ctx.iid}-staging")[1] or {}
        c.equal(get(sim, "template.settings.index.mode"), "logsdb", "new applogs data streams use logsdb")
        props = get(sim, "template.mappings.properties", {})
        c.equal({f: get(props, f"{f}.type") for f in ("service", "level", "message")},
                {"service": "keyword", "level": "keyword", "message": "text"}, "the template maps the fields")
        status, response = es.send("GET", f"/_data_stream/{p['stream']}")
        if c.check(status == 200, f"data stream {p['stream']} exists"):
            ds = response["data_streams"][0]
            c.equal(ds.get("index_mode"), "logsdb", f"{p['stream']} uses the logsdb index mode")
            c.check(get(ds, "failure_store.enabled"), f"{p['stream']} has the failure store enabled")
            es.send("POST", f"/{p['stream']}::failures/_refresh")
            good = (es.send("GET", f"/{p['stream']}/_count")[1] or {}).get("count")
            bad = (es.send("GET", f"/{p['stream']}::failures/_count")[1] or {}).get("count")
            c.equal(good, p["good"], f"{p['stream']} holds the {p['good']} valid documents")
            c.equal(bad, p["bad"], f"its failure store holds the {p['bad']} failed documents")
        status, response = es.send("GET", f"/_data_stream/{p['audit']}")
        if c.check(status == 200, f"data stream {p['audit']} still exists"):
            c.check(get(response, "data_streams.0.failure_store.enabled"), f"{p['audit']} has the failure store enabled")
        template = get(es.send("GET", f"/_index_template/{p['audit']}")[1] or {},
                       "index_templates.0.index_template", {})
        c.check(template and "data_stream_options" not in template.get("template", {}),
                f"the index template {p['audit']} is unchanged")
