import json

from lib.tasklib import Task, get
from tasks.security._helpers import as_user, count, err, send_json

PASSWORD = "stream-pass-123"


class DataStreamPrivileges(Task):
    id = "security-data-stream-privileges"
    title = "Privileges on data streams and a data stream alias: an append-only writer and a reader"
    covers = ["security.rbac.data-stream-privileges", "security.rbac.roles", "security.rbac.native-users"]
    answer = "state"

    def params(self, rnd, iid):
        app = rnd.choice(["appevents", "clickstream", "telemetry", "audittrail"])
        envs = rnd.sample(["prod", "staging", "dev", "qa", "test"], 3)
        return {"app": app, "template": f"{app}-{iid}", "pattern": f"{app}-{iid}-*",
                "streams": [f"{app}-{iid}-{e}" for e in envs[:2]], "new_stream": f"{app}-{iid}-{envs[2]}",
                "alias": f"all-{app}-{iid}", "writer_role": f"{app}-writer-{iid}",
                "reader_role": f"{app}-reader-{iid}", "writer": f"{app}-shipper-{iid}",
                "reader": f"{app}-analyst-{iid}", "docs": [rnd.randint(3, 20), rnd.randint(3, 20)]}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/_index_template/{p['template']}", {
            "index_patterns": [p["pattern"]], "data_stream": {}, "priority": 500,
            "template": {"settings": {"number_of_replicas": 1},
                         "mappings": {"properties": {"@timestamp": {"type": "date"}, "event": {"type": "keyword"}}}}})
        for stream, n in zip(p["streams"], p["docs"]):
            lines = "".join(json.dumps({"create": {}}) + "\n" +
                            json.dumps({"@timestamp": f"2026-10-01T00:00:{i:02d}Z", "event": "click"}) + "\n"
                            for i in range(n))
            es.send("POST", f"/{stream}/_bulk?refresh=true", lines.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The data streams `{p['streams'][0]}` and `{p['streams'][1]}` on cluster A hold application events
(index template `{p['template']}`, pattern `{p['pattern']}`).

  1. Create the data stream alias `{p['alias']}` that points to both data streams.
  2. Create the role `{p['writer_role']}` for the shipper that sends events: it can add new
     documents to any data stream matching `{p['pattern']}`, and creating a data stream
     automatically when it sends the first event to a new one must work too. It must not be able to
     read, overwrite or delete documents, or delete data streams.
  3. Create the role `{p['reader_role']}` that can search the events through the alias
     `{p['alias']}`, and can't write.
  4. Create the users `{p['writer']}` and `{p['reader']}` (password `{PASSWORD}` for both) with
     these roles.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST _aliases
{{
  "actions": [
    {{ "add": {{ "index": "{p['streams'][0]}", "alias": "{p['alias']}" }} }},
    {{ "add": {{ "index": "{p['streams'][1]}", "alias": "{p['alias']}" }} }}
  ]
}}

PUT _security/role/{p['writer_role']}
{{
  "indices": [
    {{ "names": ["{p['pattern']}"], "privileges": ["create_doc", "auto_configure"] }}
  ]
}}

PUT _security/role/{p['reader_role']}
{{
  "indices": [
    {{ "names": ["{p['alias']}"], "privileges": ["read"] }}
  ]
}}

PUT _security/user/{p['writer']}
{{
  "password": "{PASSWORD}",
  "roles": ["{p['writer_role']}"]
}}

PUT _security/user/{p['reader']}
{{
  "password": "{PASSWORD}",
  "roles": ["{p['reader_role']}"]
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/_alias/{p['alias']}")
        c.equal(sorted(response) if status == 200 else [], sorted(p["streams"]),
                f"the alias {p['alias']} points to both data streams")
        doc = {"@timestamp": "2026-10-02T00:00:00Z", "event": "view"}
        writer = as_user("a", p["writer"], PASSWORD)
        status, response = send_json(writer, "POST", f"/{p['streams'][0]}/_doc?refresh=true", doc)
        c.check(status == 201, f"{p['writer']} can add documents to {p['streams'][0]}", err(status, response))
        written = response if status == 201 else None
        status, response = send_json(writer, "POST", f"/{p['new_stream']}/_doc", doc)
        c.check(status == 201, f"{p['writer']} can create a new data stream {p['new_stream']} by sending a document",
                err(status, response))
        es.send("DELETE", f"/_data_stream/{p['new_stream']}")
        status, _ = count(writer, p["streams"][0])
        c.check(status == 403, f"{p['writer']} can't search the data streams", f"search returned HTTP {status}")
        if written:
            status, _ = writer.send("DELETE", f"/{written['_index']}/_doc/{written['_id']}")
            c.check(status == 403, f"{p['writer']} can't delete documents", f"delete returned HTTP {status}")
            es.send("DELETE", f"/{written['_index']}/_doc/{written['_id']}?refresh=true")
        status, response = send_json(writer, "POST", "/_security/user/_has_privileges",
                                     {"index": [{"names": p["streams"], "privileges": ["delete_index", "index"]}]})
        granted = [f"{priv} on {name}" for name, privs in get(response, "index", {}).items() for priv, v in privs.items()
                   if v]
        c.check(status == 200 and not granted, f"{p['writer']} can't delete data streams or overwrite documents",
                f"it has: {', '.join(granted)}" if granted else err(status, response))
        reader = as_user("a", p["reader"], PASSWORD)
        status, got = count(reader, p["alias"])
        c.check(status == 200 and got == sum(p["docs"]), f"{p['reader']} can search the events through {p['alias']}",
                f"HTTP {status}, {got} documents")
        status, _ = send_json(reader, "POST", f"/{p['streams'][0]}/_doc", doc)
        c.check(status == 403, f"{p['reader']} can't write", f"the write returned HTTP {status}")
