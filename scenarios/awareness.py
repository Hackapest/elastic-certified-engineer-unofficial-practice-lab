from lib.scenariolib import (KEEP_REPLICAS, check_cluster_green, check_index_intact,
                             check_new_indices_allocate, cluster_settings, create_index, Scenario)

AWARENESS = "cluster.routing.allocation.awareness.attributes"
FORCE = "cluster.routing.allocation.awareness.force.temp.values"


class Awareness(Scenario):
    id = "allocation-awareness"
    title = "New shards aren't allocated after an awareness change"
    covers = [
        "architecture.allocation.awareness", "architecture.allocation.forced-awareness",
        "cluster.health.fix-filtering", "cluster.health.allocation-explain", "cluster.health.fix-red-yellow",
        "cluster.health.cluster-settings",
    ]

    def params(self, rnd, iid):
        # missing: awareness on an attribute no node has -> nothing new is allocated (red)
        # forced: forced awareness on temp with a value no node has -> copies limited per value (yellow)
        variant = rnd.choice(["missing", "forced"])
        return {"variant": variant, "index": f"tickets-{iid}", "docs": rnd.randint(100, 400),
                "attribute": rnd.choice(["rack", "rack_id", "datacenter"]),
                "replicas": 2 if variant == "forced" else 1,
                "color": "red" if variant == "missing" else "yellow"}

    def cause(self, ctx):
        p, es = ctx.p, ctx.es
        if p["variant"] == "missing":
            cluster_settings(es, {AWARENESS: p["attribute"]})
        else:
            cluster_settings(es, {AWARENESS: "temp", FORCE: "hot,warm,cold"})
        create_index(es, p["index"], shards=1, replicas=p["replicas"], wait=None)
        es.send("GET", f"/_cluster/health/{p['index']}?wait_for_status={p['color']}&timeout=30s")
        if p["variant"] == "forced":   # the primary is allocated, so it can take documents
            create_docs = "".join(f'{{"index":{{}}}}\n{{"order":{i}}}\n' for i in range(p["docs"]))
            es.send("POST", f"/{p['index']}/_bulk?refresh=true", create_docs.encode(), "application/x-ndjson")
        else:
            p["docs"] = 0

    def brief(self, ctx):
        return (f"Cluster A turned {ctx.p['color']} after the index {ctx.p['index']} was created.\n\n"
                f"{KEEP_REPLICAS} New indices must be allocated normally too.")

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        check_index_intact(c, es, p["index"], replicas=p["replicas"], docs=p["docs"])
        check_new_indices_allocate(c, es, ctx.iid)
        check_cluster_green(c, es)

    def explain(self, ctx):
        p = ctx.p
        if p["variant"] == "missing":
            return f"""
Cause: allocation awareness is enabled on the attribute "{p['attribute']}":
  cluster.routing.allocation.awareness.attributes: "{p['attribute']}"
No node has node.attr.{p['attribute']}, and with awareness enabled a node without the attribute
can't receive new shards. Existing shards stay where they are, but nothing new can be
allocated, not even primaries: the new index is red.

How to find it:
  GET _cluster/allocation/explain         -> the "awareness" decider: node does not contain
                                             the awareness attribute [{p['attribute']}]
  GET _cluster/settings
  GET _cat/nodeattrs?v                    -> the attributes the nodes actually have (zone, temp)

Fix: remove the setting, or use an attribute the nodes have (e.g. zone).
"""
        return f"""
Cause: forced awareness on the temp attribute with a value no node has:
  cluster.routing.allocation.awareness.attributes: "temp"
  cluster.routing.allocation.awareness.force.temp.values: "hot,warm,cold"
Forced awareness spreads each shard's copies over all listed values, at most
ceil(copies / values) per value, and never allocates the share of a missing value
elsewhere. The new index has 3 copies per shard (1 primary + 2 replicas): one may go to
"hot", one to "warm", and the one meant for "cold" stays unassigned.

How to find it:
  GET _cluster/allocation/explain         -> the "awareness" decider: too many copies of the
                                             shard for the attribute value
  GET _cluster/settings
  GET _cat/nodeattrs?v

Fix: remove the forced values (or awareness entirely), or list only values that exist.
"""

    def fix(self, ctx):
        return f"""
PUT _cluster/settings
{{
  "persistent": {{
    "{AWARENESS}": null,
    "{FORCE}": null
  }}
}}
"""

    def reset(self, ctx):
        cluster_settings(ctx.es, {AWARENESS: None, FORCE: None})
        super().reset(ctx)
