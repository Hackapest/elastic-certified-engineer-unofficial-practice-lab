import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get  # noqa: E402


class CcrDataStreamExam(Task):
    id = "cluster-ccr-data-stream-exam"
    title = "Exam-style: replicate a data stream to another cluster with auto-follow"
    covers = ["cluster.ccr.auto-follow", "cluster.remote.cert-model", "data.templates.data-stream-template",
              "data.templates.data-stream-rollover"]
    size = "exam"
    answer = "state"
    cluster = "b"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        return {"stream": f"alerts-{iid}", "alias": f"primary_{iid}", "pattern": f"alerts-{iid}-follow"}

    def setup(self, ctx):
        p, a = ctx.p, ctx.es_a
        a.put(f"/_index_template/{p['stream']}", {
            "index_patterns": [f"{p['stream']}*"], "data_stream": {}, "priority": 500,
            "template": {"mappings": {"properties": {"@timestamp": {"type": "date"}, "alert": {"type": "keyword"}}}}})
        a.put(f"/_data_stream/{p['stream']}")
        a.post(f"/{p['stream']}/_doc?refresh=true", {"@timestamp": "2026-10-25T10:00:00Z", "alert": "disk full"})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The data stream `{p['stream']}` on cluster A must also be available on cluster B. Work on cluster B
(Kibana B, http://localhost:5602):

  1. Add cluster A as the persistent remote cluster `{p['alias']}` (certificate-based, sniff mode, seed es-a1:9300).
  2. Create the auto-follow pattern `{p['pattern']}` that replicates the data stream's backing indices,
     present and future, so that cluster B gets a data stream with the same name.
  3. Only backing indices created after the pattern are picked up, so roll `{p['stream']}` over on
     cluster A once, and write a document to it there.

Then check on cluster B that `{p['stream']}` exists as a replicated data stream with that document.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# On cluster B
PUT _cluster/settings
{{
  "persistent": {{ "cluster.remote.{p['alias']}.seeds": ["es-a1:9300"] }}
}}

PUT _ccr/auto_follow/{p['pattern']}
{{
  "remote_cluster": "{p['alias']}",
  "leader_index_patterns": [".ds-{p['stream']}-*"],
  "follow_index_pattern": "{{{{leader_index}}}}"
}}

# On cluster A
POST {p['stream']}/_rollover

POST {p['stream']}/_doc?refresh=true
{{ "@timestamp": "2026-10-26T10:00:00Z", "alert": "cpu high" }}
"""

    def apply_solution(self, ctx):
        text = self.solution(ctx)
        parts = h.blocks(text)
        h.run_block(*parts[0])
        h.wait_connected(ctx.es_b, ctx.p["alias"], 20)
        time.sleep(2)    # let auto-follow see the pattern before the new backing index appears
        h.run_block(*parts[1])

    def verify(self, ctx, c):
        p, b = ctx.p, ctx.es_b
        c.check(h.send(b, "GET", f"/_ccr/auto_follow/{p['pattern']}")[0] == 200, f"auto-follow pattern {p['pattern']} exists")
        stream = {}
        for _ in range(45):   # auto-follow polls the leader cluster every few seconds
            status, response = h.send(b, "GET", f"/_data_stream/{p['stream']}")
            stream = get(response, "data_streams.0", {}) if status == 200 else {}
            if stream:
                break
            time.sleep(1)
        if not c.check(stream, f"{p['stream']} exists on cluster B"):
            return
        c.check(stream.get("replicated"), "it is a replicated data stream", str(stream)[:200])
        count = 0
        for _ in range(20):
            b.send("POST", f"/{p['stream']}/_refresh")
            count = h.count(b, p["stream"]) or 0
            if count:
                break
            time.sleep(1)
        c.check(count >= 1, "the document written after the rollover arrived on cluster B", f"{count} documents")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
