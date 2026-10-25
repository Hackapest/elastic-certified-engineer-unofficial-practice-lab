from lib import client
from lib.tasklib import Task
from tasks.security._helpers import node_sh, q


class ResetPassword(Task):
    id = "security-reset-password"
    title = "Reset a native user's password with the API and with elasticsearch-reset-password"
    covers = ["security.production.reset-password", "security.rbac.native-users"]
    answer = "state"
    requires = ("shell",)

    def params(self, rnd, iid):
        return {"api_user": f"report-bot-{iid}", "api_password": f"Report-{iid}-2026",
                "tool_user": f"backup-op-{iid}", "tool_password": f"Backup-{iid}-2026",
                "node": rnd.choice(["es-a1", "es-a2", "es-a3"])}

    def setup(self, ctx):
        p = ctx.p
        for user in (p["api_user"], p["tool_user"]):
            ctx.es.put(f"/_security/user/{user}", {"password": "initial-password-1", "roles": ["viewer"]})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Two native users of cluster A need new passwords:

  1. `{p['api_user']}`: set the password `{p['api_password']}` with the security API.
  2. `{p['tool_user']}`: set the password `{p['tool_password']}` with the elasticsearch-reset-password
     command-line tool on a node (`./ece shell {p['node'][3:]}`), in interactive mode (-i) so you choose it.
     If the tool can't reach the cluster, read its error and its options (--help).

Never use the tool on `elastic` or `kibana_system` here: the lab depends on their passwords.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST _security/user/{p['api_user']}/_password
{{
  "password": "{p['api_password']}"
}}

# ./ece shell {p['node'][3:]}, then (enter the new password twice when asked):
# bin/elasticsearch-reset-password -u {p['tool_user']} -i --url https://localhost:9200
# (Without --url the tool connects to the node's IP address, which the lab's certificates
#  don't cover, and fails with "Failed to determine the health of the cluster".)
"""

    def apply_solution(self, ctx):
        p = ctx.p
        ctx.es.post(f"/_security/user/{p['api_user']}/_password", {"password": p["api_password"]})
        pw = q(p["tool_password"])
        code, out = node_sh(p["node"], f"printf 'y\\n%s\\n%s\\n' {pw} {pw} | bin/elasticsearch-reset-password "
                                       f"-u {q(p['tool_user'])} -i --url https://localhost:9200")
        return None if code == 0 else out[-400:]

    def verify(self, ctx, c):
        p = ctx.p
        for user, password in ((p["api_user"], p["api_password"]), (p["tool_user"], p["tool_password"])):
            ok = client.es("a", user=user, password=password).reachable("/_security/_authenticate")
            c.check(ok, f"{user} can log in with the new password")
            old = client.es("a", user=user, password="initial-password-1").reachable("/_security/_authenticate")
            c.check(not old, f"{user}'s old password no longer works")
