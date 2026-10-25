import time

from lib.scenariolib import check_cluster_green, check_index_intact, cluster_settings, create_index, Scenario
from lib.tasklib import get

WATERMARKS = ["cluster.routing.allocation.disk.watermark.low",
              "cluster.routing.allocation.disk.watermark.high",
              "cluster.routing.allocation.disk.watermark.flood_stage"]


def write_blocked(es, index):
    status, _ = es.send("POST", f"/{index}/_doc?refresh=true", b'{"order": -1}', "application/json")
    if status < 300:
        es.send("POST", f"/{index}/_delete_by_query?refresh=true",
                b'{"query":{"term":{"order":-1}}}', "application/json")
    return status in (403, 429)


class DiskWatermark(Scenario):
    id = "disk-flood-stage"
    title = "Writes fail with a cluster block after disk watermarks were changed"
    covers = [
        "cluster.health.fix-watermarks", "architecture.allocation.disk-watermarks", "data.index.blocks",
        "cluster.health.cluster-settings", "cluster.health.health-report",
    ]

    def params(self, rnd, iid):
        return {"index": f"payments-{iid}", "docs": rnd.randint(100, 400)}

    def cause(self, ctx):
        es = ctx.es
        create_index(es, ctx.p["index"], shards=1, replicas=1, docs=ctx.p["docs"])
        used = max(float(n["disk.percent"]) for n in es.get("/_cat/allocation?format=json&h=disk.percent")
                   if n.get("disk.percent"))
        # Watermarks below the actual usage; the flood stage blocks writes on every index
        top = max(3, int(used) - 1)
        ctx.p["levels"] = [f"{top - 2}%", f"{top - 1}%", f"{top}%"]
        cluster_settings(es, {**dict(zip(WATERMARKS, ctx.p["levels"])), "cluster.info.update.interval": "10s"})
        for _ in range(45):
            if write_blocked(es, ctx.p["index"]):
                break
            time.sleep(1)

    def brief(self, ctx):
        return f"""
Writes to the index {ctx.p['index']} on cluster A fail. Try it:

POST {ctx.p['index']}/_doc
{{ "order": 1 }}

Fix it so that documents can be written to it again, and it stays that way: the problem
must not come back by itself. Don't delete any documents.
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        # The flood stage is re-checked every few seconds; give a half-done fix time to relapse
        time.sleep(12)
        status, response = es.send("POST", f"/{p['index']}/_doc", b'{"order": 1}', "application/json")
        c.check(status < 300, f"documents can be written to {p['index']}",
                f"HTTP {status}: {get(response, 'error.reason', response)}")
        if status < 300:
            es.send("POST", f"/{p['index']}/_delete_by_query?refresh=true",
                    b'{"query":{"term":{"order":1}}}', "application/json")
        blocked = es.get("/_all/_settings/index.blocks.read_only_allow_delete?expand_wildcards=all")
        still = [i for i, s in blocked.items() if get(s, "settings.index.blocks.read_only_allow_delete") == "true"]
        c.check(not still, "no index has a read_only_allow_delete block",
                f"still blocked: {', '.join(still[:5])}")
        check_index_intact(c, es, p["index"], replicas=1, docs=p["docs"])
        check_cluster_green(c, es)

    def explain(self, ctx):
        low, high, flood = ctx.p["levels"]
        return f"""
Cause: the disk watermarks were set below the disks' actual usage:
  cluster.routing.allocation.disk.watermark.low:          {low}
  cluster.routing.allocation.disk.watermark.high:         {high}
  cluster.routing.allocation.disk.watermark.flood_stage:  {flood}
Above the flood stage, Elasticsearch puts an index.blocks.read_only_allow_delete block on
every index with a shard on that node, so writes fail with a cluster_block_exception.
(Above the high watermark it also moves shards away; above the low one it stops
allocating new shards there.)

How to find it:
  The write error names the block: "index [...] blocked by: [TOO_MANY_REQUESTS/12/disk
  usage exceeded flood-stage watermark, index has read-only-allow-delete block]".
  GET _health_report                      -> the disk indicator
  GET _cat/allocation?v                   -> disk.percent per node
  GET _cluster/settings                   -> the watermark settings

Fix: put the watermarks back (remove them to get the defaults: 85%, 90%, 95%). Elasticsearch
removes the block by itself once usage is below the high watermark again; you can also
remove it with PUT */_settings {{"index.blocks.read_only_allow_delete": null}}.
Removing only the block doesn't help: it comes back at the next disk check.
"""

    def fix(self, ctx):
        return """
PUT _cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.disk.watermark.low": null,
    "cluster.routing.allocation.disk.watermark.high": null,
    "cluster.routing.allocation.disk.watermark.flood_stage": null
  }
}

PUT */_settings?expand_wildcards=all
{
  "index.blocks.read_only_allow_delete": null
}
"""

    def reset(self, ctx):
        es = ctx.es
        cluster_settings(es, {**{w: None for w in WATERMARKS}, "cluster.info.update.interval": None})
        es.send("PUT", "/*/_settings?expand_wildcards=all", b'{"index.blocks.read_only_allow_delete": null}',
                "application/json")
        super().reset(ctx)
