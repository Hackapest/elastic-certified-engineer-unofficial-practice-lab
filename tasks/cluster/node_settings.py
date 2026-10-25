from lib import nodes
from lib.tasklib import Task, get


class NodeSettings(Task):
    id = "cluster-node-settings"
    title = "Change static node settings in elasticsearch.yml and restart the node"
    covers = ["cluster.maintenance.node-settings", "architecture.allocation.builtin-attributes"]
    answer = "state"
    cluster = "b"
    requires = ("shell",)

    def params(self, rnd, iid):
        return {"node": rnd.choice(["es-b2", "es-b3"]), "rack": f"rack-{rnd.choice(['r1', 'r7', 'r12'])}",
                "buffer": rnd.choice(["15%", "20%"])}

    def prompt(self, ctx):
        p = ctx.p
        n = p["node"][3:]
        return f"""
Node `{p['node']}` of cluster B was moved to a new rack. Configure it with:

  - the custom node attribute `rack` with the value "{p['rack']}"
  - an indexing buffer of {p['buffer']} of the heap (indices.memory.index_buffer_size)

Both are static settings: put them in the node's elasticsearch.yml (`./ece config {n}`) and restart
the node (`./ece restart {n}`). Afterwards cluster B must be green again with all 3 nodes.
"""

    def solution(self, ctx):
        p = ctx.p
        n = p["node"][3:]
        return f"""
# ./ece config {n}   and add:
node.attr.rack: {p['rack']}
indices.memory.index_buffer_size: {p['buffer']}
# then: ./ece restart {n}

GET _cat/nodeattrs?v
GET _nodes/{p['node']}/settings?filter_path=**.indices.memory,**.attr
"""

    def apply_solution(self, ctx):
        p = ctx.p
        nodes.set_settings(p["node"], {"node.attr.rack": p["rack"], "indices.memory.index_buffer_size": p["buffer"]})
        return None if nodes.restart(p["node"]) else "the node didn't rejoin"

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        settings = es.get(f"/_nodes/{p['node']}/settings").get("nodes", {})
        node = next(iter(settings.values()), {})
        c.equal(get(node, "attributes.rack"), p["rack"], f"{p['node']} has the attribute rack={p['rack']}")
        c.equal(get(node, "settings.indices.memory.index_buffer_size"), p["buffer"],
                f"{p['node']} uses an indexing buffer of {p['buffer']}")
        health = es.send("GET", "/_cluster/health?wait_for_status=green&timeout=90s", timeout=120)[1] or {}
        c.equal((health.get("number_of_nodes"), health.get("status")), (3, "green"), "cluster B is green with 3 nodes")

    def cleanup(self, ctx):
        nodes.restore(ctx.p["node"])
