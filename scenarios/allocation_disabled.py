from lib.scenariolib import (KEEP_REPLICAS, check_cluster_green, check_index_intact,
                             check_new_indices_allocate, cluster_settings, create_index, Scenario)

# (value of cluster.routing.allocation.enable, resulting health of a new index)
VARIANTS = [("none", "red"), ("primaries", "yellow"), ("new_primaries", "yellow")]


class AllocationDisabled(Scenario):
    id = "allocation-disabled"
    title = "New indices aren't allocated after shard allocation was restricted"
    covers = [
        "cluster.health.fix-allocation-disabled", "cluster.health.allocation-explain",
        "cluster.health.cluster-settings", "architecture.allocation.allocation-enable",
        "cluster.health.fix-red-yellow",
    ]

    def params(self, rnd, iid):
        value, color = rnd.choice(VARIANTS)
        return {"value": value, "color": color, "old": f"orders-{iid}", "new": f"events-{iid}",
                "docs": rnd.randint(100, 500)}

    def cause(self, ctx):
        p, es = ctx.p, ctx.es
        create_index(es, p["old"], shards=2, replicas=1, docs=p["docs"])
        cluster_settings(es, {"cluster.routing.allocation.enable": p["value"]})
        create_index(es, p["new"], shards=2, replicas=1, wait=None)

    def brief(self, ctx):
        return (f"Cluster A turned {ctx.p['color']} after the index {ctx.p['new']} was created.\n\n"
                f"{KEEP_REPLICAS} New indices must be allocated normally too.")

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        check_index_intact(c, es, p["old"], replicas=1, docs=p["docs"])
        check_index_intact(c, es, p["new"], replicas=1, docs=0)
        check_new_indices_allocate(c, es, ctx.iid)
        check_cluster_green(c, es)

    def explain(self, ctx):
        p = ctx.p
        return f"""
Cause: the persistent cluster setting
  cluster.routing.allocation.enable: "{p['value']}"
restricts which shards may be allocated ("all" is the default). Shards that were already
allocated stay where they are, but the shards of the new index {p['new']} can't all be
allocated, so the cluster is {p['color']}.

How to find it:
  GET _cluster/allocation/explain         -> the "enable" decider says allocation is
                                             restricted by cluster.routing.allocation.enable
  GET _cluster/settings                   -> shows the setting

Setting it to "all" or removing it (null) fixes it. This setting is normally only changed
temporarily, e.g. during a rolling restart.
"""

    def fix(self, ctx):
        return """
PUT _cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.enable": null
  }
}
"""

    def reset(self, ctx):
        cluster_settings(ctx.es, {"cluster.routing.allocation.enable": None})
        super().reset(ctx)
