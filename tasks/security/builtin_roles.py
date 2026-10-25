from lib.sampledata import FLIGHTS
from lib.tasklib import Task, get
from tasks.security._helpers import as_user, count, err, send_json

PASSWORD = "builtin-pass-123"


def has_privileges(user, request):
    status, response = send_json(user, "POST", "/_security/user/_has_privileges", request)
    return response if status == 200 else {}


class BuiltinRoles(Task):
    id = "security-builtin-roles"
    title = "Give users access with built-in roles only"
    covers = ["security.rbac.builtin", "security.rbac.native-users", "security.rbac.check-privileges"]
    answer = "state"

    def params(self, rnd, iid):
        return {"editor": f"{rnd.choice(['dash', 'kibana', 'analyst'])}-{iid}",
                "ingest": f"{rnd.choice(['pipelines', 'ingest', 'onboarding'])}-{iid}",
                "backup": f"{rnd.choice(['backup', 'snapshots', 'dr'])}-{iid}",
                "pipeline": f"test-pipeline-{iid}"}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create three users on cluster A, all with the password `{PASSWORD}`. Give each of them only
built-in roles (don't create any role), and not more access than needed:

  1. `{p['editor']}` works in Kibana: full access to all Kibana features in all spaces, and read-only
     access to the data indices.
  2. `{p['ingest']}` manages ingest pipelines and index templates, and has no access to the data.
  3. `{p['backup']}` takes snapshots of all indices and can see the snapshot repositories, but can't
     restore snapshots, register or remove repositories, or read the data.
"""

    def solution(self, ctx):
        p = ctx.p
        return "\n".join(f"""
PUT _security/user/{user}
{{
  "password": "{PASSWORD}",
  "roles": ["{role}"]
}}""" for user, role in ((p["editor"], "editor"), (p["ingest"], "ingest_admin"), (p["backup"], "snapshot_user")))

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        builtin = {name for name, role in es.get("/_security/role").items() if get(role, "metadata._reserved")}
        users = {}
        for key in ("editor", "ingest", "backup"):
            name = p[key]
            status, response = es.send("GET", f"/_security/user/{name}")
            if not c.check(status == 200, f"user {name} exists"):
                continue
            roles = response[name]["roles"]
            c.check(roles and set(roles) <= builtin, f"{name} only has built-in roles",
                    f"roles: {roles}; not built in: {sorted(set(roles) - builtin)}")
            users[key] = as_user("a", name, PASSWORD)
        kibana_all = {"application": [{"application": "kibana-.kibana", "resources": ["space:default", "space:other"],
                                       "privileges": ["all"]}]}
        if "editor" in users:
            u, name = users["editor"], p["editor"]
            status, got = count(u, FLIGHTS)
            c.check(status == 200 and got, f"{name} can read data indices", f"search returned HTTP {status}")
            status, _ = send_json(u, "POST", f"/{FLIGHTS}/_doc", {"x": 1})
            c.check(status == 403, f"{name} can't write to data indices", f"the write returned HTTP {status}")
            c.check(get(has_privileges(u, kibana_all), "has_all_requested"), f"{name} has all Kibana privileges")
            c.check(not get(has_privileges(u, {"cluster": ["manage", "manage_security"]}), "cluster.manage", True),
                    f"{name} can't manage the cluster")
        if "ingest" in users:
            u, name = users["ingest"], p["ingest"]
            status, response = send_json(u, "PUT", f"/_ingest/pipeline/{p['pipeline']}", {"processors": []})
            c.check(status == 200, f"{name} can create ingest pipelines", err(status, response))
            es.send("DELETE", f"/_ingest/pipeline/{p['pipeline']}")
            c.check(get(has_privileges(u, {"cluster": ["manage_index_templates"]}), "has_all_requested"),
                    f"{name} can manage index templates")
            status, _ = count(u, FLIGHTS)
            c.check(status == 403, f"{name} can't read data", f"search returned HTTP {status}")
            c.check(not get(has_privileges(u, kibana_all), "has_all_requested", True),
                    f"{name} has no full Kibana access")
        if "backup" in users:
            u, name = users["backup"], p["backup"]
            r = has_privileges(u, {"cluster": ["create_snapshot", "cluster:admin/repository/get",
                                               "cluster:admin/snapshot/restore", "cluster:admin/repository/put",
                                               "cluster:admin/repository/delete"]})
            cl = r.get("cluster", {})
            c.check(cl.get("create_snapshot") and cl.get("cluster:admin/repository/get"),
                    f"{name} can create snapshots and see repositories", f"privileges: {cl}")
            denied = [k for k in ("cluster:admin/snapshot/restore", "cluster:admin/repository/put",
                                  "cluster:admin/repository/delete") if cl.get(k, True)]
            c.check(not denied, f"{name} can't restore snapshots or manage repositories", f"allowed: {denied}")
            status, _ = count(u, FLIGHTS)
            c.check(status == 403, f"{name} can't read data", f"search returned HTTP {status}")
