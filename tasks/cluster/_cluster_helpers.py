"""Shared helpers for the cluster-* templates (snapshots, remote clusters, CCS, CCR).

The task loader skips files starting with "_", so this module only holds helpers.

Multi-cluster solutions: by default selftest applies a solution by running its text on
`task.cluster` only. Tasks whose solution spans both clusters (or needs the node shell, like
keystore entries) mark each part with a line "# On cluster A" / "# On cluster B" and override
`Task.apply_solution(ctx)` with run_blocks() and friends.
"""

import json
import random
import re
import subprocess
import time

from lib import client, config, tasklib
from lib.tasklib import get

SNAPSHOT_ROOT = "/usr/share/elasticsearch/snapshots"
NODES = {"a": ("es-a1", "es-a2", "es-a3"), "b": ("es-b1", "es-b2", "es-b3")}
TRANSPORT_SEED = {"a": "es-a1:9300", "b": "es-b1:9300"}


def es(cluster):
    return client.es(cluster)


def send(es_client, method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    return es_client.send(method, path, data, "application/json" if body is not None else None, timeout=timeout)


def must(es_client, method, path, body=None, timeout=120):
    status, response = send(es_client, method, path, body, timeout)
    if status >= 300:
        raise RuntimeError(f"{method} {path} failed with HTTP {status}: {tasklib.short_error(response)}")
    return response


# --- Data -----------------------------------------------------------------------

def bulk(es_client, index, docs, mappings=None, settings=None):
    body = {"settings": settings or {"number_of_shards": 1, "number_of_replicas": 0}}
    if mappings:
        body["mappings"] = {"properties": mappings}
    must(es_client, "PUT", f"/{index}", body)
    if docs:
        lines = "".join(json.dumps({"index": {"_index": index, "_id": str(i + 1)}}) + "\n" + json.dumps(d) + "\n"
                        for i, d in enumerate(docs))
        status, response = es_client.send("POST", "/_bulk?refresh=true", lines.encode(), "application/x-ndjson")
        if status >= 300 or response.get("errors"):
            raise RuntimeError(f"bulk into {index} failed: {str(response)[:300]}")


def count(es_client, index):
    status, response = send(es_client, "GET", f"/{index}/_count")
    return response.get("count") if status == 200 else None


SALES_MAPPING = {"@timestamp": {"type": "date"}, "store": {"type": "keyword"}, "country": {"type": "keyword"},
                 "category": {"type": "keyword"}, "quantity": {"type": "integer"},
                 "price": {"type": "double"}, "channel": {"type": "keyword"}}
CATEGORIES = ["shoes", "jackets", "bags", "shirts", "watches"]
CHANNELS = ["online", "store"]
STORES = {
    "a": [("Berlin", "DE"), ("Paris", "FR"), ("Madrid", "ES"), ("Rome", "IT")],
    "b": [("Chicago", "US"), ("Toronto", "CA"), ("Boston", "US"), ("Denver", "US")],
}


def sales_docs(seed, cluster, n=240):
    """Deterministic sales documents; each cluster has its own stores, the same categories."""
    rnd = random.Random(f"{seed}-{cluster}")
    docs = []
    for i in range(n):
        store, country = rnd.choice(STORES[cluster])
        docs.append({
            "@timestamp": f"2026-09-{1 + i % 28:02d}T{rnd.randrange(8, 20):02d}:{rnd.randrange(60):02d}:00Z",
            "store": store, "country": country, "category": rnd.choice(CATEGORIES),
            "quantity": rnd.randint(1, 9), "price": round(rnd.uniform(5, 400), 2),
            "channel": rnd.choice(CHANNELS),
        })
    return docs


# --- Remote clusters --------------------------------------------------------------

def set_remote(es_client, alias, seeds, skip_unavailable=None, wait=True):
    settings = {f"cluster.remote.{alias}.seeds": seeds}
    if skip_unavailable is not None:
        settings[f"cluster.remote.{alias}.skip_unavailable"] = skip_unavailable
    must(es_client, "PUT", "/_cluster/settings", {"persistent": settings})
    if wait:
        wait_connected(es_client, alias)


def wait_connected(es_client, alias, seconds=20):
    deadline = time.time() + seconds
    while time.time() < deadline:
        # resolve/cluster opens the connection if it isn't open yet
        send(es_client, "GET", f"/_resolve/cluster/{alias}:*")
        info = send(es_client, "GET", "/_remote/info")[1] or {}
        if get(info, f"{alias}.connected"):
            return True
        time.sleep(1)
    return False


def remote_settings(es_client, alias):
    """Flat persistent and transient settings of a remote alias."""
    response = send(es_client, "GET", "/_cluster/settings?flat_settings=true")[1] or {}
    prefix = f"cluster.remote.{alias}."
    pick = lambda d: {k[len(prefix):]: v for k, v in (d or {}).items() if k.startswith(prefix)}
    return pick(response.get("persistent")), pick(response.get("transient"))


def remove_remotes(iid):
    """Remove every remote alias containing the iid, persistent and transient, on both clusters."""
    for cluster in ("a", "b"):
        e = es(cluster)
        response = send(e, "GET", "/_cluster/settings?flat_settings=true")[1] or {}
        for scope in ("persistent", "transient"):
            aliases = {m.group(1) for k in (response.get(scope) or {})
                       for m in [re.match(r"cluster\.remote\.([^.]+)\.", k)] if m and iid in m.group(1)}
            if aliases:
                send(e, "PUT", "/_cluster/settings", {scope: {f"cluster.remote.{a}.*": None for a in aliases}})


def remote_connected(es_client, alias, seconds=15):
    return wait_connected(es_client, alias, seconds)


# --- CCR ------------------------------------------------------------------------------

def remove_auto_follow(iid):
    for cluster in ("a", "b"):
        e = es(cluster)
        response = send(e, "GET", "/_ccr/auto_follow")[1] or {}
        for pattern in response.get("patterns", []):
            if iid in pattern["name"]:
                send(e, "DELETE", f"/_ccr/auto_follow/{pattern['name']}")


def follow_info(es_client, index):
    status, response = send(es_client, "GET", f"/{index}/_ccr/info")
    if status != 200:
        return None
    infos = response.get("follower_indices", [])
    return infos[0] if infos else None


def wait_for(predicate, seconds=20, interval=1):
    deadline = time.time() + seconds
    while True:
        value = predicate()
        if value or time.time() >= deadline:
            return value
        time.sleep(interval)


# --- Snapshots -----------------------------------------------------------------------

def remove_snapshot_files(iid):
    """Generic cleanup unregisters repositories but leaves their files: remove directories named
    with the iid in a/, b/ and shared/ (one volume shared by all nodes)."""
    if not re.fullmatch(r"[0-9a-z]{2,12}", iid):
        return
    subprocess.run(["docker", "compose", "--project-directory", str(config.ROOT), "exec", "-T", "es-a1",
                    "find", SNAPSHOT_ROOT, "-mindepth", "2", "-maxdepth", "2", "-name", f"*{iid}*",
                    "-exec", "rm", "-rf", "{}", "+"], capture_output=True, text=True, check=False)


def repository(es_client, name):
    status, response = send(es_client, "GET", f"/_snapshot/{name}")
    return response.get(name) if status == 200 else None


def snapshot_info(es_client, repo, snap):
    status, response = send(es_client, "GET", f"/_snapshot/{repo}/{snap}")
    if status != 200:
        return None
    snaps = response.get("snapshots", [])
    return snaps[0] if snaps else None


def location_matches(repo, location):
    """The repository location as given in the task: relative to path.repo, or absolute."""
    got = (get(repo or {}, "settings.location") or "").rstrip("/")
    return got in (location, f"{SNAPSHOT_ROOT}/{location}")


# --- Keystore and API keys ---------------------------------------------------------

def docker_exec(node, *args, stdin=None):
    return subprocess.run(["docker", "compose", "--project-directory", str(config.ROOT), "exec", "-T", node, *args],
                          input=stdin, capture_output=True, text=True, check=False)


def keystore_add(cluster, name, value):
    for node in NODES[cluster]:
        result = docker_exec(node, "bin/elasticsearch-keystore", "add", "-x", "-f", name, stdin=value)
        if result.returncode != 0:
            raise RuntimeError(f"keystore add on {node} failed: {result.stderr.strip()[:300]}")


def remove_keystore_entries(iid):
    for cluster in ("a", "b"):
        removed = False
        for node in NODES[cluster]:
            listing = docker_exec(node, "bin/elasticsearch-keystore", "list").stdout.split()
            for name in listing:
                if iid in name:
                    docker_exec(node, "bin/elasticsearch-keystore", "remove", name)
                    removed = True
        if removed:
            send(es(cluster), "POST", "/_nodes/reload_secure_settings")


def invalidate_api_keys(iid):
    for cluster in ("a", "b"):
        e = es(cluster)
        response = send(e, "GET", "/_security/api_key?active_only=true")[1] or {}
        ids = [k["id"] for k in response.get("api_keys", []) if iid in (k.get("name") or "")]
        if ids:
            send(e, "DELETE", "/_security/api_key", {"ids": ids})


# --- Multi-cluster solutions -----------------------------------------------------------

MARKER = re.compile(r"^#\s*On cluster ([AB])\b", re.IGNORECASE)


def blocks(text):
    """Split a solution into [(cluster, console text)] at "# On cluster A|B" lines."""
    parts, cluster, lines = [], None, []
    for line in text.splitlines():
        m = MARKER.match(line.strip())
        if m:
            if cluster and any(l.strip() and not l.strip().startswith("#") for l in lines):
                parts.append((cluster, "\n".join(lines)))
            cluster, lines = m.group(1).lower(), []
        else:
            lines.append(line)
    if cluster and any(l.strip() and not l.strip().startswith("#") for l in lines):
        parts.append((cluster, "\n".join(lines)))
    return parts


def run_block(cluster, text):
    results, error = tasklib.run_console(es(cluster), text)
    if error:
        raise RuntimeError(f"on cluster {cluster.upper()}: {error}")
    return results


def run_blocks(text):
    return [(cluster, run_block(cluster, part)) for cluster, part in blocks(text)]


def full_cleanup(iid, keystore=False, snapshots=False, api_keys=False):
    remove_auto_follow(iid)
    remove_remotes(iid)
    if keystore:
        remove_keystore_entries(iid)
    if api_keys:
        invalidate_api_keys(iid)
    if snapshots:
        remove_snapshot_files(iid)


def duration_ms(value):
    """'2s', '500ms', '1m' -> milliseconds; '-1' -> -1; None if unparseable."""
    if value is None:
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(nanos|micros|ms|s|m|h|d)?", str(value).strip())
    if not m:
        return None
    if m.group(1) == "-1":
        return -1
    factor = {"nanos": 1e-6, "micros": 1e-3, "ms": 1, "s": 1000, "m": 60000, "h": 3600000, "d": 86400000,
              None: 1}[m.group(2)]
    return float(m.group(1)) * factor


def cron_fields(schedule):
    """Normalize a cron expression to (seconds, minutes, hours, day-of-month, month, day-of-week),
    treating '*' and '?' as the same in the day fields."""
    parts = (schedule or "").split()
    if len(parts) < 6:
        return None
    parts = [p.upper() for p in parts[:6]]
    for i in (3, 4, 5):
        if parts[i] in ("*", "?"):
            parts[i] = "*"
    return tuple(str(int(p)) if p.isdigit() else p for p in parts)


def setup_sales(ctx, index, n=240):
    """The same sales index name on both clusters, with different stores (and so countries)."""
    for cluster in ("a", "b"):
        bulk(es(cluster), index, sales_docs(ctx.iid, cluster, n), SALES_MAPPING)
