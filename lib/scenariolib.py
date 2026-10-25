"""Troubleshooting scenarios: break a cluster, let the user diagnose and fix it.

A scenario is a subclass of Scenario in scenarios/<name>.py. Like tasks, the
seed picks a variant and the resources it creates carry the instance ID.
"""

from . import config, tasklib

SCENARIOS_DIR = config.ROOT / "scenarios"


class Scenario:
    id = None
    title = ""
    covers = []
    cluster = "a"
    requires = ()

    def params(self, rnd, iid):
        return {}

    def brief(self, ctx):
        """The symptom as the user sees it. Must not give away the cause."""
        raise NotImplementedError

    def cause(self, ctx):
        """Break the cluster."""
        raise NotImplementedError

    def verify(self, ctx, c):
        """Add checks to c: healthy again, and the cause fixed rather than worked around."""
        raise NotImplementedError

    def explain(self, ctx):
        raise NotImplementedError

    def fix(self, ctx):
        """Reference fix in console syntax (shown by explain, used by selftest)."""
        raise NotImplementedError

    def apply_fix(self, ctx):
        """Apply the reference fix (selftest). Override when the fix isn't only API calls."""
        _, error = tasklib.run_console(ctx.es, self.fix(ctx))
        return error

    def reset(self, ctx):
        """Undo the scenario. The default removes everything named with the instance ID."""
        tasklib.cleanup_resources(ctx.es, ctx.iid)


def load():
    return tasklib.load_templates(SCENARIOS_DIR, Scenario)


# --- Helpers for scenarios -----------------------------------------------------

KEEP_REPLICAS = ("Fix it so that the cluster is green again, and every index keeps its current number "
                 "of replicas and all of its documents.")


def create_index(es, name, shards=1, replicas=1, settings=None, docs=0, wait="green"):
    """Create an index, optionally fill it with documents, and wait for a health status."""
    # Don't wait for active shards: in a broken cluster the primaries may never start
    es.put(f"/{name}?wait_for_active_shards=0", {"settings": {"number_of_shards": shards,
                                                              "number_of_replicas": replicas, **(settings or {})}})
    if wait:
        es.send("GET", f"/_cluster/health/{name}?wait_for_status={wait}&timeout=60s")
    if docs:
        bulk = "".join(f'{{"index":{{}}}}\n{{"order":{i},"amount":{i % 97}}}\n' for i in range(docs))
        es.send("POST", f"/{name}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")


def cluster_settings(es, settings):
    """Set (or with None, reset) persistent cluster settings."""
    es.put("/_cluster/settings", {"persistent": settings})


def health(es, index=None, wait_seconds=5):
    """Health status after waiting up to wait_seconds for green (408 on timeout still has a body)."""
    path = f"/_cluster/health/{index}" if index else "/_cluster/health"
    _, response = es.send("GET", f"{path}?wait_for_status=green&timeout={wait_seconds}s")
    return (response or {}).get("status")


def check_index_intact(c, es, index, replicas, docs):
    """The usual outcome checks: index exists, green, replicas kept, documents kept."""
    if not c.check(tasklib.exists(es, f"/{index}"), f"index {index} still exists"):
        return False
    c.equal(health(es, index), "green", f"index {index} is green")
    settings = tasklib.index_settings(es, index) or {}
    c.equal(settings.get("index.number_of_replicas"), str(replicas), f"index {index} has {replicas} replica(s)")
    if docs:
        c.equal(es.get(f"/{index}/_count")["count"], docs, f"index {index} has all its documents")
    return True


def check_cluster_green(c, es):
    """Outcome check for the whole cluster; allows time for shards to settle after a fix."""
    return c.equal(health(es, wait_seconds=20), "green", "the cluster is green")


def check_new_indices_allocate(c, es, iid):
    """Outcome check: a fresh index with a replica gets fully allocated."""
    probe = f"probe-{iid}"
    es.send("DELETE", f"/{probe}")
    status, response = es.send("PUT", f"/{probe}?wait_for_active_shards=0", b'{"settings":{"number_of_replicas":1}}',
                               "application/json")
    if status != 200:
        c.fail("new indices can be created and allocated", tasklib.short_error(response))
    else:
        c.equal(health(es, probe, 10), "green", "new indices are allocated (a test index turns green)")
    es.send("DELETE", f"/{probe}")
