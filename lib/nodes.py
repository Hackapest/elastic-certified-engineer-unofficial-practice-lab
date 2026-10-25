"""Node-level operations for tasks and scenarios: edit elasticsearch.yml, restart, restore.

Every container holds the lab's original node configs in /usr/share/elasticsearch/ece-config/
(baked into the image), so restoring a node's config is exact.
"""

import re
import time

from . import client, docker, lab

ORIGINAL = "/usr/share/elasticsearch/ece-config/{node}.yml"
CLUSTER_NODES = {"a": ["es-a1", "es-a2", "es-a3"], "b": ["es-b1", "es-b2", "es-b3"]}


def cluster_of(node):
    return node[3]


def read(node):
    return lab.read_node_config(node)


def write(node, text):
    lab.write_node_config(node, text)


def original(node):
    """The lab's original config of a node."""
    result = docker.compose("exec", "-T", node, "cat", ORIGINAL.format(node=node), check=False, capture=True)
    if result.returncode == 0:
        return result.stdout
    # The node isn't running: read it from the image instead
    result = docker.compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "cat", node,
                            ORIGINAL.format(node=node), capture=True)
    return result.stdout


def setting(text, key):
    """Value of a top-level `key: value` line, or None."""
    for line in text.splitlines():
        m = re.match(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$", line)
        if m:
            return m.group(1).strip('"\'')
    return None


def with_settings(text, settings):
    """Config text with the given settings set (value None removes them)."""
    keys = set(settings)
    lines = [l for l in text.splitlines() if not any(re.match(rf"^\s*{re.escape(k)}\s*:", l) for k in keys)]
    for key, value in settings.items():
        if value is not None:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def set_settings(node, settings):
    write(node, with_settings(read(node), settings))


def wait_joined(cluster, nodes=3, seconds=180):
    """Wait until the cluster has `nodes` nodes and isn't red. Returns True on success."""
    es = client.es(cluster)
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            status, health = es.send("GET", f"/_cluster/health?wait_for_nodes={nodes}&timeout=10s", timeout=20)
            if status == 200 and health.get("number_of_nodes") == nodes and health.get("status") != "red":
                return True
        except OSError:
            pass   # the node behind the cluster's port may be the one restarting
        time.sleep(3)
    return False


def restart(node, wait=True):
    docker.compose("restart", node, capture=True)
    return wait_joined(cluster_of(node)) if wait else True


def running(node):
    return node in docker.running_services()


def restore(node, restart_if_changed=True):
    """Put the lab's original config back; restart the node if it changed or isn't running."""
    wanted = original(node)
    changed = read(node) != wanted
    if changed:
        write(node, wanted)
    if not running(node):
        docker.compose("start", node, capture=True)
        wait_joined(cluster_of(node))
    elif changed and restart_if_changed:
        restart(node)
    return changed


def start_times(cluster):
    """{node name: JVM start time in ms} for the nodes of a cluster."""
    status, response = client.es(cluster).send("GET", "/_nodes/jvm?filter_path=nodes.*.name,nodes.*.jvm.start_time_in_millis")
    return {n["name"]: n["jvm"]["start_time_in_millis"] for n in (response or {}).get("nodes", {}).values()}
