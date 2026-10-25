import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task  # noqa: E402


class ClusterSettingsRemote(Task):
    id = "cluster-settings-persistent-transient"
    title = "Tidy up persistent and transient cluster settings, resetting with null"
    covers = ["cluster.health.cluster-settings", "cluster.remote.settings"]
    answer = "state"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        return {
            "old": f"{rnd.choice(['legacy', 'old_dc', 'retired'])}_{iid}",
            "tmp": f"{rnd.choice(['tmp', 'trial', 'test'])}_{iid}",
            "main": f"{rnd.choice(['main', 'prod', 'primary'])}_{iid}",
            "tmp_seed": rnd.choice(["es-b2:9300", "es-b3:9300"]),
            "ping": rnd.choice(["15s", "30s", "1m"]),
            "probe": f"{rnd.choice(['probe', 'drill', 'check'])}_{iid}",
        }

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        h.must(es, "PUT", "/_cluster/settings", {
            "persistent": {
                f"cluster.remote.{p['old']}.seeds": ["es-b1:9300"],
                f"cluster.remote.{p['old']}.skip_unavailable": True,
                f"cluster.remote.{p['main']}.seeds": ["es-b1:9300"],
                f"cluster.remote.{p['main']}.skip_unavailable": False,
                f"cluster.remote.{p['main']}.transport.compress": True,
            },
            "transient": {
                f"cluster.remote.{p['tmp']}.seeds": [p["tmp_seed"]],
                f"cluster.remote.{p['tmp']}.skip_unavailable": True,
            },
        })

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster A has three remote clusters configured: `{p['old']}`, `{p['main']}` and `{p['tmp']}`.
Look at how their settings are stored (persistent or transient), then:

  1. Remove `{p['old']}` completely.
  2. `{p['tmp']}` was added as transient settings, which are lost on a full cluster restart.
     Make it permanent: the same seed node, stored persistently, and no transient settings left
     for it. Its skip_unavailable must go back to the default (not set at all).
  3. On `{p['main']}`, remove the transport.compress setting so that it falls back to its
     default, and add a persistent ping interval of {p['ping']} (transport.ping_schedule). Leave
     its other settings unchanged.
  4. Add `{p['probe']}` for a test today only, so that it disappears on the next full cluster
     restart: seed node es-b3:9300, and skip_unavailable set to true.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET _cluster/settings?flat_settings=true

PUT _cluster/settings
{{
  "persistent": {{
    "cluster.remote.{p['old']}.*": null,
    "cluster.remote.{p['tmp']}.seeds": ["{p['tmp_seed']}"],
    "cluster.remote.{p['main']}.transport.compress": null,
    "cluster.remote.{p['main']}.transport.ping_schedule": "{p['ping']}"
  }},
  "transient": {{
    "cluster.remote.{p['tmp']}.*": null,
    "cluster.remote.{p['probe']}.seeds": ["es-b3:9300"],
    "cluster.remote.{p['probe']}.skip_unavailable": true
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        persistent, transient = h.remote_settings(es, p["old"])
        c.check(not persistent and not transient, f"{p['old']} is removed", f"{persistent or transient}")
        persistent, transient = h.remote_settings(es, p["tmp"])
        if persistent.get("mode") == "sniff":
            persistent.pop("mode")
        c.equal(persistent, {"seeds": [p["tmp_seed"]]}, f"{p['tmp']} is persistent with only its seed")
        c.equal(transient, {}, f"{p['tmp']} has no transient settings")
        persistent, transient = h.remote_settings(es, p["main"])
        ping = persistent.pop("transport.ping_schedule", None)
        c.equal(persistent, {"seeds": ["es-b1:9300"], "skip_unavailable": "false"},
                f"{p['main']} keeps its seed and skip_unavailable, without transport.compress")
        c.equal(h.duration_ms(ping), h.duration_ms(p["ping"]), f"{p['main']} has a persistent ping schedule of {p['ping']}")
        c.equal(transient, {}, f"{p['main']} has no transient settings")
        persistent, transient = h.remote_settings(es, p["probe"])
        if transient.get("mode") == "sniff":
            transient.pop("mode")
        c.equal(persistent, {}, f"{p['probe']} has no persistent settings")
        c.equal(transient, {"seeds": ["es-b3:9300"], "skip_unavailable": "true"},
                f"{p['probe']} is transient with its seed and skip_unavailable true")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
