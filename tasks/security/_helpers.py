"""Shared helpers for the security templates (not a template: the loader skips files starting with _)."""

import json
import shlex
import subprocess
import time

from lib import client, config, console
from lib.sampledata import ECOMMERCE
from lib.tasklib import get, short_error, temp_copy

NODES = {"a": ("es-a1", "es-a2", "es-a3"), "b": ("es-b1", "es-b2", "es-b3")}
KIBANA_HEADERS = {"kbn-xsrf": "true", "x-elastic-internal-origin": "Kibana"}


# --- Acting as someone else -------------------------------------------------------

def as_user(cluster, user, password, headers=None):
    c = client.es(cluster, user=user, password=password)
    c.headers.update(headers or {})
    return c


def as_api_key(cluster, encoded):
    c = client.es(cluster)
    c.headers["Authorization"] = f"ApiKey {encoded}"
    return c


def kibana_as(cluster, user, password):
    return client.Client(config.kibana_url(cluster), user, password, headers=KIBANA_HEADERS)


def body(obj):
    return json.dumps(obj).encode()


def send_json(c, method, path, obj=None):
    return c.send(method, path, body(obj) if obj is not None else None, "application/json")


def count(c, index, query=None):
    """(HTTP status, number of matching docs or None)."""
    status, response = send_json(c, "POST", f"/{index}/_count", {"query": query} if query else None)
    return status, (response or {}).get("count") if status == 200 else None


def search(c, index, query=None, size=100, **extra):
    req = {"size": size, "track_total_hits": True, **extra}
    if query:
        req["query"] = query
    return send_json(c, "POST", f"/{index}/_search", req)


def err(status, response):
    reason = get(response, "error.reason") if isinstance(response, dict) else None
    return f"HTTP {status}" + (f": {str(reason)[:200]}" if reason else "")


def try_write(c, admin, index, doc):
    """Try to index a document as `c`. Returns the status; removes the document again if it was written."""
    status, response = send_json(c, "POST", f"/{index}/_doc?refresh=true", doc)
    if status < 300 and isinstance(response, dict) and response.get("_id"):
        admin.send("DELETE", f"/{response['_index']}/_doc/{response['_id']}?refresh=true")
    return status


def can_authenticate(cluster, user, password):
    status, response = as_user(cluster, user, password).send("GET", "/_security/_authenticate")
    return status == 200, response


# --- Data --------------------------------------------------------------------------

def setup_orders(es, index, docs):
    error = temp_copy(es, ECOMMERCE, index)
    if error:
        raise RuntimeError(error)
    es.post("/_reindex?refresh=true", {"source": {"index": ECOMMERCE}, "dest": {"index": index}, "max_docs": docs},
            timeout=120)


def _prune(value):
    """Drop empty objects, which source filtering keeps and field-level security removes."""
    if isinstance(value, dict):
        pruned = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in pruned.items() if v != {}}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def same_sources(c, user, es, index, includes, excludes, message, query=None):
    """The user's view of each document equals the admin's view with the same source filter."""
    sort = [{"order_id": "asc"}]
    status, got = search(user, index, query, size=50, sort=sort)
    if not c.check(status == 200, f"the user can search {index}", err(status, got)):
        return False
    source = {"includes": includes or ["*"], "excludes": excludes or []}
    _, want = search(es, index, query, size=50, sort=sort, _source=source)
    got_docs = {h["_id"]: _prune(h.get("_source", {})) for h in get(got, "hits.hits", [])}
    want_docs = {h["_id"]: _prune(h.get("_source", {})) for h in get(want, "hits.hits", [])}
    for doc_id, doc in want_docs.items():
        if got_docs.get(doc_id) != doc:
            extra = sorted(set(got_docs.get(doc_id, {})) - set(doc))
            missing = sorted(set(doc) - set(got_docs.get(doc_id, {})))
            return c.fail(message, f"document {doc_id}: " + (f"visible but not allowed: {extra}; " if extra else "")
                          + (f"missing: {missing}" if missing else "a field shows the wrong sub-fields"))
    return c.check(bool(want_docs), message)


# --- API keys -----------------------------------------------------------------------

def api_keys(es, name_pattern, active_only=False):
    q = {"bool": {"filter": [{"wildcard": {"name": name_pattern}}]}}
    if active_only:
        q["bool"]["filter"].append({"term": {"invalidated": False}})
    status, response = send_json(es, "POST", "/_security/_query/api_key?with_limited_by=false",
                                 {"query": q, "size": 1000})
    return response.get("api_keys", []) if status == 200 else []


def invalidate_keys(es, iid):
    ids = [k["id"] for k in api_keys(es, f"*{iid}*", active_only=True)]
    if ids:
        send_json(es, "DELETE", "/_security/api_key", {"ids": ids})


class Probe:
    """An API key with the same role descriptors as a key under test, to test what they allow
    (the secret of the user's key isn't available to the checker)."""

    def __init__(self, cluster, es, iid, role_descriptors):
        self.es = es
        status, response = send_json(es, "POST", "/_security/api_key",
                                     {"name": f"probe-{iid}", "expiration": "1h",
                                      "role_descriptors": role_descriptors or {}})
        self.ok = status == 200
        self.error = None if self.ok else err(status, response)
        self.id = response.get("id") if self.ok else None
        self.client = as_api_key(cluster, response["encoded"]) if self.ok else None

    def close(self):
        if self.id:
            send_json(self.es, "DELETE", "/_security/api_key", {"ids": [self.id]})


# --- Kibana -----------------------------------------------------------------------

def run_kibana_console(kibana, text, es=None):
    """Run console text where requests to Kibana use the Dev Tools `kbn:` prefix (POST kbn:/api/...).
    Other requests go to Elasticsearch (`es`). Returns an error message or None."""
    try:
        requests = console.parse(text)
    except console.ConsoleSyntaxError as e:
        return f"Could not parse: {e}"
    for req in requests:
        target, path = (kibana, req.path[len("/kbn:"):]) if req.path.startswith("/kbn:") else (es, req.path)
        status, response = target.send(req.method, path, body(req.body) if req.body is not None else None,
                                       "application/json")
        if status >= 400:
            return f"{req.method} {path} failed with HTTP {status}: {short_error(response)}"
    return None


def delete_spaces(kibana, iid):
    status, spaces = kibana.send("GET", "/api/spaces/space")
    if status == 200:
        for space in spaces:
            if iid in space["id"]:
                kibana.send("DELETE", f"/api/spaces/space/{space['id']}")


# --- Node containers -----------------------------------------------------------

def node_sh(node, script, check=False, timeout=120):
    """Run a bash script inside a node container (as the elasticsearch user, in the ES home directory).
    Returns (exit code, stdout + stderr)."""
    cmd = ["docker", "compose", "--project-directory", str(config.ROOT), "exec", "-T", node, "bash", "-c", script]
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode != 0:
        raise RuntimeError(f"{node}: {script[:80]}... failed: {result.stdout}{result.stderr}")
    return result.returncode, result.stdout + result.stderr


def q(value):
    return shlex.quote(str(value))


def keystore_list(node):
    code, out = node_sh(node, "bin/elasticsearch-keystore list")
    return out.split() if code == 0 else []


def keystore_show(node, setting):
    code, out = node_sh(node, f"bin/elasticsearch-keystore show {q(setting)}")
    return out.strip() if code == 0 else None


def keystore_add(node, setting, value):
    node_sh(node, f"printf %s {q(value)} | bin/elasticsearch-keystore add -x -f {q(setting)}", check=True)


def keystore_remove_matching(node, text):
    for setting in keystore_list(node):
        if text in setting:
            node_sh(node, f"bin/elasticsearch-keystore remove {q(setting)}")


def file_users(node):
    code, out = node_sh(node, "cat config/users")
    return [line.split(":", 1)[0] for line in out.splitlines() if ":" in line] if code == 0 else []


def file_user_roles(node, user):
    code, out = node_sh(node, f"bin/elasticsearch-users roles {q(user)}")
    return out


def remove_file_users(node, iid):
    for user in file_users(node):
        if iid in user:
            node_sh(node, f"bin/elasticsearch-users userdel {q(user)}")


def curl_in_node(node, path, user, password, host="localhost"):
    """Authenticate against a node from inside its container. Returns (HTTP status, parsed body)."""
    script = (f"f=$(mktemp); curl -s -o $f -w '%{{http_code}}' --cacert config/certs/ca/ca.crt "
              f"-u {q(user + ':' + password)} https://{host}:9200{path}; echo; cat $f; rm -f $f")
    code, out = node_sh(node, script)
    first, _, rest = out.partition("\n")
    try:
        return int(first.strip()), json.loads(rest) if rest.strip() else None
    except ValueError:
        return 0, out


def wait_for(fn, seconds=15, interval=1.0):
    """Call fn until it returns a truthy value or the time runs out; returns the last value."""
    deadline = time.time() + seconds
    while True:
        value = fn()
        if value or time.time() > deadline:
            return value
        time.sleep(interval)
