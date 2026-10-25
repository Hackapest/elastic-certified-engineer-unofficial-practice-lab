from lib.tasklib import Task, get

ACCOUNTS = ["elastic/fleet-server", "elastic/kibana"]


def tokens(es, account):
    status, response = es.send("GET", f"/_security/service/{account}/credential")
    return set(get(response, "tokens", {}) or {}) if status == 200 else set()


class ServiceTokens(Task):
    id = "security-service-tokens"
    title = "Create and delete service account tokens"
    covers = ["security.rbac.service-accounts"]
    answer = "state"

    def params(self, rnd, iid):
        account = rnd.choice(ACCOUNTS)
        site = rnd.choice(["berlin", "lisbon", "oslo", "madrid"])
        return {"account": account, "new": f"{site}-{iid}", "old": f"legacy-{iid}"}

    def setup(self, ctx):
        p = ctx.p
        ctx.es.post(f"/_security/service/{p['account']}/credential/token/{p['old']}")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
On cluster A:

  1. Create a token named `{p['new']}` for the service account `{p['account']}`. (The token value is
     shown only once: in real life you would store it in the client's configuration.)
  2. Delete the token `{p['old']}` of the same service account, which is no longer used.
  3. Look at the privileges the service account gets (the get service accounts API).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST _security/service/{p['account']}/credential/token/{p['new']}

DELETE _security/service/{p['account']}/credential/token/{p['old']}

GET _security/service/{p['account']}/credential

GET _security/service/{p['account']}
"""

    def verify(self, ctx, c):
        p = ctx.p
        names = tokens(ctx.es, p["account"])
        c.check(p["new"] in names, f"{p['account']} has a token named {p['new']}")
        c.check(p["old"] not in names, f"the token {p['old']} is deleted")

    def cleanup(self, ctx):
        for account in ACCOUNTS:
            for name in tokens(ctx.es, account):
                if ctx.iid in name:
                    ctx.es.send("DELETE", f"/_security/service/{account}/credential/token/{name}")
