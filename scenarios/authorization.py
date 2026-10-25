from lib import client, config
from lib.scenariolib import Scenario, create_index
from lib.tasklib import get

PASSWORD = "analyst-pass"

# (variant, description for explain)
VARIANTS = {
    "index-pattern": "the role grants read on a misspelled index pattern",
    "privilege": "the role grants the wrong privilege (view_index_metadata instead of read)",
    "role-name": "the user is assigned a role that doesn't exist (a misspelled role name)",
}


class Authorization(Scenario):
    id = "user-cannot-search"
    title = "A user gets a security exception when searching"
    covers = [
        "security.rbac.troubleshoot-authz", "security.rbac.roles", "security.rbac.native-users",
        "security.rbac.check-privileges",
    ]

    def params(self, rnd, iid):
        return {"variant": rnd.choice(sorted(VARIANTS)), "index": f"sales-{iid}", "user": f"analyst-{iid}",
                "role": f"sales-reader-{iid}", "docs": rnd.randint(50, 300)}

    def cause(self, ctx):
        p, es = ctx.p, ctx.es
        create_index(es, p["index"], shards=1, replicas=1, docs=p["docs"])
        names = [p["index"].replace("sales-", "sale-") + "*"] if p["variant"] == "index-pattern" else [p["index"]]
        privileges = ["view_index_metadata"] if p["variant"] == "privilege" else ["read"]
        es.put(f"/_security/role/{p['role']}", {"indices": [{"names": names, "privileges": privileges}]})
        role = p["role"].replace("reader", "readers") if p["variant"] == "role-name" else p["role"]
        es.put(f"/_security/user/{p['user']}", {"password": PASSWORD, "roles": [role]})

    def as_user(self, ctx):
        return client.es(ctx.task.cluster, user=ctx.p["user"], password=PASSWORD)

    def brief(self, ctx):
        p = ctx.p
        ca = config.CA_CERT.relative_to(config.ROOT) if config.CA_CERT.is_relative_to(config.ROOT) else config.CA_CERT
        return f"""
The user {p['user']} (password: {PASSWORD}) can't search the index {p['index']} on cluster A.
Try it as that user, from a terminal in the repository folder:

  curl --cacert {ca} -u {p['user']}:{PASSWORD} "https://localhost:9200/{p['index']}/_search?size=0"

Fix it so that {p['user']} can search {p['index']}, but still can't write to it and can't
read any other index.
"""

    def verify(self, ctx, c):
        p, user = ctx.p, self.as_user(ctx)
        status, response = user.send("GET", f"/{p['index']}/_search?size=0&track_total_hits=true")
        c.check(status == 200 and get(response, "hits.total.value") == p["docs"],
                f"{p['user']} can search {p['index']} and sees all documents",
                f"HTTP {status}: {get(response, 'error.reason', response)}" if status != 200
                else f"sees {get(response, 'hits.total.value')} of {p['docs']} documents")
        status, _ = user.send("POST", f"/{p['index']}/_doc", b'{"order": -1}', "application/json")
        c.check(status == 403, f"{p['user']} can't write to {p['index']}",
                f"the write returned HTTP {status}" + (" (the document was written)" if status < 300 else ""))
        if status < 300:
            ctx.es.send("POST", f"/{p['index']}/_delete_by_query?refresh=true",
                        b'{"query":{"term":{"order":-1}}}', "application/json")
        status, _ = user.send("GET", "/kibana_sample_data_flights/_search?size=0")
        c.check(status == 403, f"{p['user']} can't read other indices",
                f"searching kibana_sample_data_flights returned HTTP {status}")

    def explain(self, ctx):
        p = ctx.p
        return f"""
Cause: {VARIANTS[p['variant']]}.

How to find it:
  The error names the user, their roles and the missing privilege:
  "action [indices:data/read/search] is unauthorized for user [{p['user']}] with effective
  roles [...] on indices [{p['index']}]". A role that doesn't exist is silently ignored,
  so it's missing from "effective roles".
  GET _security/user/{p['user']}
  GET _security/role/{p['role']}

Fix: the role must grant "read" on {p['index']}, and the user must have that role. Don't
give the user a broad built-in role: it must not be able to write or read anything else.
"""

    def fix(self, ctx):
        p = ctx.p
        return f"""
PUT _security/role/{p['role']}
{{
  "indices": [
    {{ "names": ["{p['index']}"], "privileges": ["read"] }}
  ]
}}

PUT _security/user/{p['user']}
{{
  "roles": ["{p['role']}"]
}}
"""
