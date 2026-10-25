from lib.tasklib import Task
from tasks.security._helpers import curl_in_node, file_users, node_sh, q, remove_file_users

NODES = ["es-a1", "es-a2", "es-a3"]


class FileRealm(Task):
    id = "security-file-realm"
    title = "Emergency users in the file realm with elasticsearch-users"
    covers = ["security.rbac.file-realm", "security.rbac.builtin"]
    answer = "state"
    requires = ("shell",)

    def params(self, rnd, iid):
        return {"user": f"ops-{iid}", "password": f"S3cure-{iid}-pw", "role": rnd.choice(["monitoring_user", "viewer"]),
                "old_user": f"tmp-{iid}"}

    def setup(self, ctx):
        p = ctx.p
        for node in NODES:
            node_sh(node, f"bin/elasticsearch-users useradd {q(p['old_user'])} -p temp-password-1 -r viewer",
                    check=True)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster A needs a user that works even when the security index is unavailable: a user in the
file realm, defined on every node. On all three nodes of cluster A (`./ece shell a1`, a2, a3):

  1. Add the file realm user `{p['user']}` with the password `{p['password']}` and the built-in role `{p['role']}`.
  2. Remove the old file realm user `{p['old_user']}`.

No restart is needed: the file realm reloads its files automatically. Check that you can
authenticate as `{p['user']}` on each node (e.g. curl ... -u {p['user']}:... https://localhost:9200/_security/_authenticate).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# On each node of cluster A: ./ece shell a1, then a2, then a3
bin/elasticsearch-users useradd {p['user']} -p {p['password']} -r {p['role']}
bin/elasticsearch-users userdel {p['old_user']}
bin/elasticsearch-users list
"""

    def apply_solution(self, ctx):
        p = ctx.p
        for node in NODES:
            code, out = node_sh(node, f"bin/elasticsearch-users useradd {q(p['user'])} -p {q(p['password'])} "
                                      f"-r {q(p['role'])} && bin/elasticsearch-users userdel {q(p['old_user'])}")
            if code:
                return f"{node}: {out}"
        return None

    def verify(self, ctx, c):
        p = ctx.p
        for node in NODES:
            users = file_users(node)
            c.check(p["old_user"] not in users, f"{node}: {p['old_user']} is removed")
            if not c.check(p["user"] in users, f"{node}: {p['user']} is a file realm user"):
                continue
            ok = False
            for _ in range(10):   # the file realm picks up changes within a few seconds
                status, body = curl_in_node(node, "/_security/_authenticate", p["user"], p["password"])
                ok = status == 200 and (body or {}).get("authentication_realm", {}).get("type") == "file"
                if ok:
                    break
                node_sh(node, "sleep 1")
            c.check(ok, f"{node}: {p['user']} authenticates through the file realm",
                    f"HTTP {status}: {str(body)[:200]}")
            if ok:
                c.check(p["role"] in (body or {}).get("roles", []), f"{node}: {p['user']} has the role {p['role']}",
                        f"roles: {(body or {}).get('roles')}")

    def cleanup(self, ctx):
        for node in NODES:
            remove_file_users(node, ctx.iid)
