from lib import nodes
from lib.tasklib import Task

WARM_ROLES = ["master", "data_warm", "data_cold", "ingest", "remote_cluster_client"]


class NodeRoles(Task):
    id = "architecture-node-roles"
    title = "Turn a node into a dedicated warm/cold node with node.roles"
    covers = ["architecture.stack.node-roles", "architecture.stack.node-roles-concepts", "architecture.allocation.data-tiers",
              "cluster.maintenance.node-settings"]
    answer = "state"
    cluster = "b"
    requires = ("shell",)

    def params(self, rnd, iid):
        return {"node": rnd.choice(["es-b2", "es-b3"])}

    def prompt(self, ctx):
        p = ctx.p
        n = p["node"][3:]
        return f"""
Node `{p['node']}` of cluster B has all the default roles. Make it a node that:

  - stays master-eligible
  - holds data of the warm and cold tiers only (no hot, no content, no frozen tier)
  - can run ingest pipelines and connect to remote clusters
  - has no machine learning and no transform role

Roles are set in elasticsearch.yml (`./ece config {n}`, then `./ece restart {n}`). Data that may
no longer live on the node moves away by itself. Afterwards cluster B must be green with all 3 nodes.
"""

    def solution(self, ctx):
        p = ctx.p
        n = p["node"][3:]
        return f"""
# ./ece config {n}   and add:
node.roles: [ {", ".join(WARM_ROLES)} ]
# then: ./ece restart {n}

GET _cat/nodes?v&h=name,node.role,master
"""

    def apply_solution(self, ctx):
        nodes.set_settings(ctx.p["node"], {"node.roles": f"[ {', '.join(WARM_ROLES)} ]"})
        return None if nodes.restart(ctx.p["node"]) else "the node didn't rejoin"

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        info = es.get(f"/_nodes/{p['node']}?filter_path=nodes.*.roles").get("nodes", {})
        roles = sorted(next(iter(info.values()), {}).get("roles", []))
        c.equal(roles, sorted(WARM_ROLES), f"{p['node']} has exactly the requested roles")
        health = es.send("GET", "/_cluster/health?wait_for_status=green&timeout=90s", timeout=120)[1] or {}
        c.equal((health.get("number_of_nodes"), health.get("status")), (3, "green"), "cluster B is green with 3 nodes")

    def cleanup(self, ctx):
        nodes.restore(ctx.p["node"])
