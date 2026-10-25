from lib.scenariolib import (KEEP_REPLICAS, check_cluster_green, check_index_intact,
                             check_new_indices_allocate, cluster_settings, create_index, Scenario)

# Cluster-level exclusions that leave a single eligible node: (setting suffix, value)
VARIANTS = [("exclude._name", "es-a2,es-a3"), ("exclude._name", "es-a1,es-a3"),
            ("exclude.zone", "zone-1,zone-2"), ("exclude.temp", "hot")]


class ClusterFilter(Scenario):
    id = "yellow-cluster-allocation-filter"
    title = "Replicas unassigned after nodes were excluded from allocation"
    covers = [
        "architecture.allocation.cluster-filtering", "cluster.health.fix-filtering",
        "cluster.health.allocation-explain", "cluster.health.cluster-settings", "cluster.maintenance.remove-node",
    ]

    def params(self, rnd, iid):
        setting, value = rnd.choice(VARIANTS)
        return {"setting": f"cluster.routing.allocation.{setting}", "value": value,
                "index": f"shipments-{iid}", "docs": rnd.randint(100, 600)}

    def cause(self, ctx):
        p, es = ctx.p, ctx.es
        cluster_settings(es, {p["setting"]: p["value"]})
        create_index(es, p["index"], shards=2, replicas=1, docs=p["docs"], wait="yellow")

    def brief(self, ctx):
        return (f"Cluster A is yellow.\n\n"
                f"{KEEP_REPLICAS} New indices must be allocated normally too.")

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        check_index_intact(c, es, p["index"], replicas=1, docs=p["docs"])
        check_new_indices_allocate(c, es, ctx.iid)
        check_cluster_green(c, es)

    def explain(self, ctx):
        p = ctx.p
        return f"""
Cause: a cluster-level allocation filter excludes all nodes but one:
  {p['setting']}: "{p['value']}"
This is how you drain nodes before taking them out of the cluster: their shards move
elsewhere and nothing new is allocated to them. With only one eligible node, new replicas
can't be allocated (a primary and its replica never share a node).

How to find it:
  GET _cluster/allocation/explain         -> the "filter" decider: node matches cluster
                                             setting [{p['setting']}]
  GET _cluster/settings

Fix: remove the exclusion (set it to null).
"""

    def fix(self, ctx):
        return f"""
PUT _cluster/settings
{{
  "persistent": {{
    "{ctx.p['setting']}": null
  }}
}}
"""

    def reset(self, ctx):
        cluster_settings(ctx.es, {ctx.p["setting"]: None})
        super().reset(ctx)
