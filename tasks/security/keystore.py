from lib.tasklib import Task, get
from tasks.security._helpers import NODES, keystore_add, keystore_list, keystore_remove_matching, keystore_show, \
    node_sh, q


class Keystore(Task):
    id = "security-keystore"
    title = "Add, check and remove secure settings in the keystore of every node, then reload them"
    covers = ["security.production.keystore"]
    answer = "state"
    requires = ("shell",)

    def params(self, rnd, iid):
        client = f"{rnd.choice(['backup', 'archive', 'snapshots'])}{iid}"
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ234567"
        return {"client": client, "access_key": f"s3.client.{client}.access_key",
                "secret_key": f"s3.client.{client}.secret_key",
                "access": "AKIA" + "".join(rnd.choice(letters) for _ in range(16)),
                "secret": "".join(rnd.choice(letters.lower() + letters) for _ in range(32)),
                "legacy": f"s3.client.legacy{iid}.secret_key",
                "legacy_access": f"s3.client.legacy{iid}.access_key"}

    def setup(self, ctx):
        # A complete (if unused) S3 client: an S3 client with a secret but no access key makes the
        # node refuse to start, so a half-removed client must never be left behind on a restart.
        for node in NODES["a"]:
            keystore_add(node, ctx.p["legacy_access"], "AKIALEGACYLEGACY0000")
            keystore_add(node, ctx.p["legacy"], "old-secret-value")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Snapshots of cluster A will go to an S3 bucket through the S3 client `{p['client']}`. Its
credentials are secure settings, so they belong in the Elasticsearch keystore of each node.

On all three nodes of cluster A (es-a1, es-a2, es-a3; open a shell with `./ece shell a1` etc.):

  1. Add the secure setting `{p['access_key']}` with the value `{p['access']}`
     and `{p['secret_key']}` with the value `{p['secret']}`.
  2. Remove the S3 client `legacy{ctx.iid}`, which is no longer used: both of its secure settings,
     `{p['legacy_access']}` and `{p['legacy']}`. (Never leave half a client behind:
     an S3 client with only one of the two keys stops the node from starting.)
  3. List the keystore entries to check the result.

Then make the running nodes load the new values without a restart.
"""

    def commands(self, p):
        return [f"echo -n '{p['access']}' | bin/elasticsearch-keystore add -x {p['access_key']}",
                f"echo -n '{p['secret']}' | bin/elasticsearch-keystore add -x {p['secret_key']}",
                f"bin/elasticsearch-keystore remove {p['legacy_access']} {p['legacy']}",
                "bin/elasticsearch-keystore list"]

    def solution(self, ctx):
        p = ctx.p
        lines = "\n".join(self.commands(p))
        return f"""
# On each node of cluster A: ./ece shell a1, then a2, then a3
# (bin/elasticsearch-keystore add {p['access_key']} prompts for the value; -x reads it from stdin)
{lines}

# Then, in Dev Tools:
POST _nodes/reload_secure_settings
"""

    def apply_solution(self, ctx):
        p = ctx.p
        for node in NODES["a"]:
            keystore_add(node, p["access_key"], p["access"])
            keystore_add(node, p["secret_key"], p["secret"])
            code, out = node_sh(node, f"bin/elasticsearch-keystore remove {q(p['legacy_access'])} {q(p['legacy'])}")
            if code:
                return f"{node}: {out}"
        status, response = ctx.es.send("POST", "/_nodes/reload_secure_settings")
        return None if status == 200 else str(response)[:300]

    def verify(self, ctx, c):
        p = ctx.p
        for node in NODES["a"]:
            entries = keystore_list(node)
            if not c.check(entries, f"{node}: the keystore can be read"):
                continue
            for setting, value in ((p["access_key"], p["access"]), (p["secret_key"], p["secret"])):
                if c.check(setting in entries, f"{node}: the keystore has {setting}"):
                    got = keystore_show(node, setting)
                    c.check(got == value, f"{node}: {setting} has the right value",
                            "the value differs (check for a trailing newline or a typo)")
            left = [e for e in (p["legacy"], p["legacy_access"]) if e in entries]
            c.check(not left, f"{node}: the legacy S3 client is removed", f"still there: {', '.join(left)}")

    def cleanup(self, ctx):
        for node in NODES["a"] + NODES["b"]:
            keystore_remove_matching(node, ctx.iid)
