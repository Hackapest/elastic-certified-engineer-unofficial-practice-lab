import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get, index_settings  # noqa: E402


class CcrManage(Task):
    id = "cluster-ccr-manage"
    title = "Pause, resume and unfollow follower indices"
    covers = ["cluster.ccr.pause-resume", "cluster.ccr.unfollow", "cluster.ccr.disaster-recovery"]
    answer = "state"
    cluster = "b"
    requires = ("cluster-b",)

    def params(self, rnd, iid):
        names = ["stock", "prices", "vendors", "returns"]
        rnd.shuffle(names)
        return {"alias": f"cluster_a_{iid}", "pause": f"{names[0]}-{iid}", "resume": f"{names[1]}-{iid}",
                "promote": f"{names[2]}-{iid}", "requests": rnd.choice([4, 6, 8]),
                "poll": rnd.choice(["10s", "30s", "2m"])}

    def followers(self, p):
        return [p["pause"], p["resume"], p["promote"]]

    def setup(self, ctx):
        p, a, b = ctx.p, ctx.es_a, ctx.es_b
        h.set_remote(b, p["alias"], [h.TRANSPORT_SEED["a"]])
        for i, index in enumerate(self.followers(p)):
            h.bulk(a, index, h.sales_docs(f"{ctx.iid}{i}", "a", 40), h.SALES_MAPPING)
            h.must(b, "PUT", f"/{index}-f/_ccr/follow?wait_for_active_shards=1",
                   {"remote_cluster": p["alias"], "leader_index": index})
        h.wait_for(lambda: all(h.count(b, f"{i}-f") == 40 for i in self.followers(p)), 20)
        h.must(b, "POST", f"/{p['resume']}-f/_ccr/pause_follow")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster B has three follower indices that replicate cluster A's indices of the same name
(without the "-f") through the remote cluster `{p['alias']}`: `{p['pause']}-f`,
`{p['resume']}-f` and `{p['promote']}-f`. Look at their state with the follower info API.

On cluster B:
  1. Stop replicating `{p['pause']}-f` for now, in a way that can be resumed later; it must
     remain a follower index.
  2. `{p['resume']}-f` was paused. Resume it, with at most {p['requests']} outstanding read
     requests and a read poll timeout of {p['poll']}.
  3. `{p['promote']}` is being moved to cluster B for good: turn `{p['promote']}-f` into a
     regular index that accepts writes, keeping all its documents.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# On cluster B
GET */_ccr/info

POST {p['pause']}-f/_ccr/pause_follow

POST {p['resume']}-f/_ccr/resume_follow
{{
  "max_outstanding_read_requests": {p['requests']},
  "read_poll_timeout": "{p['poll']}"
}}

POST {p['promote']}-f/_ccr/pause_follow
POST {p['promote']}-f/_close
POST {p['promote']}-f/_ccr/unfollow
POST {p['promote']}-f/_open
"""

    def verify(self, ctx, c):
        p, b = ctx.p, ctx.es_b
        info = h.follow_info(b, f"{p['pause']}-f")
        c.check(info and info.get("status") == "paused", f"{p['pause']}-f is a paused follower", str(info)[:200])
        info = h.follow_info(b, f"{p['resume']}-f")
        if c.check(info and info.get("status") == "active", f"{p['resume']}-f is following again", str(info)[:200]):
            c.equal(get(info, "parameters.max_outstanding_read_requests"), p["requests"],
                    f"with at most {p['requests']} outstanding read requests")
            c.equal(h.duration_ms(get(info, "parameters.read_poll_timeout")), h.duration_ms(p["poll"]),
                    f"with a read poll timeout of {p['poll']}")
        index = f"{p['promote']}-f"
        settings = index_settings(b, index)
        if not c.check(settings, f"{index} exists"):
            return
        c.check(h.follow_info(b, index) is None and "index.xpack.ccr.following_index" not in settings,
                f"{index} is no longer a follower index")
        state = h.send(b, "GET", f"/_cluster/state/metadata/{index}?filter_path=metadata.indices.*.state")[1]
        c.equal(get(state or {}, f"metadata.indices.{index}.state"), "open", f"{index} is open")
        c.equal(h.count(b, index), 40, f"{index} kept its documents")
        marker = f"check-{int(time.time())}"
        status, _ = h.send(b, "PUT", f"/{index}/_doc/{marker}?refresh=true", {"store": marker})
        c.check(status in (200, 201), f"{index} accepts writes")
        if status in (200, 201):
            h.send(b, "DELETE", f"/{index}/_doc/{marker}?refresh=true")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
