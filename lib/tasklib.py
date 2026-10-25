"""Task templates, instances, grading helpers and the template loader.

A template is a subclass of Task in tasks/<domain>/<name>.py. An instance is a
template plus a seed: the seed drives params(), and every resource the instance
creates carries its instance ID (iid) in its name, so instances can coexist and
be cleaned up.
"""

import importlib.util
import json
import random
import secrets
from pathlib import Path

from . import client, config, console, taxonomy

TASKS_DIR = config.ROOT / "tasks"
BROKEN = {}   # template files that failed to load: path -> error (filled by load_templates)


class Task:
    id = None              # stable template ID, e.g. "data-products-mapping"
    title = ""
    covers = []            # taxonomy entry IDs
    size = "drill"         # "drill" or "exam"
    answer = "state"       # "state": graded by inspecting the cluster; "query": by running the answer
    compare = "hits"       # query tasks: "hits", "hits_ordered", "hits_scored", "aggs", "esql"
                           # (or override grade())
    cluster = "a"
    requires = ()          # "shell", "ml", "kibana", "cluster-b"

    def params(self, rnd, iid):
        return {}

    def setup(self, ctx):
        pass

    def prompt(self, ctx):
        raise NotImplementedError

    def solution(self, ctx):
        raise NotImplementedError

    def verify(self, ctx, c):
        """State tasks: add checks to c."""
        raise NotImplementedError

    def grade(self, ctx, c, answer, reference):
        """Query tasks: compare the last response of the answer with the reference's."""
        if self.compare == "hits":
            same_hits(c, answer, reference, ordered=False)
        elif self.compare == "hits_ordered":
            same_hits(c, answer, reference, ordered=True)
        elif self.compare == "hits_scored":
            same_hits(c, answer, reference, ordered=True)
            same_scores(c, answer, reference)
        elif self.compare == "aggs":
            same_aggs(c, answer, reference)
        elif self.compare == "esql":
            same_esql(c, answer, reference)
        else:
            raise ValueError(f"unknown compare mode {self.compare}")

    def wrong_answer(self, ctx):
        """Optional: a plausible but wrong answer, used by selftest to prove grading can fail."""
        return None

    def apply_solution(self, ctx):
        """Apply the reference solution (selftest). Returns an error message or None. Override when
        the solution has steps that aren't API calls (node shell commands, values from responses)."""
        _, error = run_console(ctx.es, self.solution(ctx))
        return error

    def cleanup(self, ctx):
        """Optional: remove what the generic cleanup doesn't know about (auto-follow patterns,
        remote cluster settings, API keys, ...). Runs after the generic cleanup on drop and selftest."""


class Context:
    def __init__(self, task, iid, params):
        self.task, self.iid, self.p = task, iid, params

    @property
    def es(self):
        return client.es(self.task.cluster)

    @property
    def es_a(self):
        return client.es("a")

    @property
    def es_b(self):
        return client.es("b")

    def kibana(self, cluster=None):
        return client.kibana(cluster or self.task.cluster)


class Checker:
    def __init__(self):
        self.results = []   # (ok, message, detail)

    def check(self, ok, message, detail=None):
        self.results.append((bool(ok), message, None if ok else detail))
        return bool(ok)

    def equal(self, actual, expected, message):
        return self.check(actual == expected, message, f"expected {expected!r}, found {actual!r}")

    def fail(self, message, detail=None):
        return self.check(False, message, detail)

    @property
    def passed(self):
        return bool(self.results) and all(ok for ok, _, _ in self.results)

    def report(self):
        lines = []
        for ok, message, detail in self.results:
            lines.append(f"  {'✔' if ok else '✘'} {message}")
            if detail:
                lines.append(f"      {detail}")
        return "\n".join(lines)


# --- Loading ------------------------------------------------------------------

def load_templates(directory=TASKS_DIR, base=Task):
    templates = {}
    for path in sorted(Path(directory).rglob("*.py")):
        if path.name.startswith("_"):
            continue
        name = f"_ece_{directory.name}_" + "_".join(path.relative_to(directory).with_suffix("").parts)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:  # one broken template file must not break the whole CLI
            BROKEN[str(path.relative_to(config.ROOT))] = f"{type(e).__name__}: {e}"
            continue
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, base) and obj is not base and obj.id:
                if obj.id in templates:
                    raise SystemExit(f"Duplicate template id {obj.id} in {path}")
                templates[obj.id] = obj()
    return templates


def validate_templates(templates):
    known = {e.full_id for e in taxonomy.entries(taxonomy.load())}
    problems = []
    for t in templates.values():
        for entry in t.covers:
            if entry not in known:
                problems.append(f"{t.id}: covers unknown taxonomy entry {entry}")
        if not isinstance(t, Task):
            continue
        if t.answer not in ("state", "query"):
            problems.append(f"{t.id}: answer must be 'state' or 'query'")
        if t.size not in ("drill", "exam"):
            problems.append(f"{t.id}: size must be 'drill' or 'exam'")
    return problems


def new_iid(existing):
    while True:
        iid = secrets.token_hex(2)
        if iid not in existing and not iid.isdigit():
            return iid


def make_params(task, seed, iid):
    return task.params(random.Random(seed), iid)


# --- Running answers and solutions -------------------------------------------

def run_console(es, text):
    """Parse and run console text. Returns (results, error message or None)."""
    try:
        requests = console.parse(text)
    except console.ConsoleSyntaxError as e:
        return [], f"Could not parse: {e}"
    results = console.run(es, requests)
    for req, status, response in results:
        if status >= 400:
            return results, f"{req} failed with HTTP {status}: {short_error(response)}"
    return results, None


def short_error(response):
    if isinstance(response, dict) and isinstance(response.get("error"), dict):
        err = response["error"]
        root = (err.get("root_cause") or [err])[0]
        return f"{root.get('type')}: {root.get('reason')}"
    return str(response)[:300]


# --- Helpers for verify() ------------------------------------------------------

def get(data, path, default=None):
    """get(d, "a.b.0.c") walks dicts and lists."""
    for part in path.split("."):
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return default
    return data


def exists(es, path):
    status, _ = es.send("HEAD", path)
    return status == 200


def field_mapping(es, index, field):
    """Mapping of a field by dotted path, following properties and multi-fields. None if absent."""
    status, response = es.send("GET", f"/{index}/_mapping")
    if status != 200:
        return None
    mapping = next(iter(response.values()))["mappings"]
    node = mapping
    for part in field.split("."):
        children = {**node.get("properties", {}), **node.get("fields", {})}
        if part not in children:
            return None
        node = children[part]
    return node


def analyze(es, index, text, analyzer=None, field=None, normalizer=None):
    """Tokens produced by an index's analyzer, field or normalizer (None if the request fails)."""
    body = {"text": text}
    for key, value in (("analyzer", analyzer), ("field", field), ("normalizer", normalizer)):
        if value:
            body[key] = value
    status, response = es.send("POST", f"/{index}/_analyze", json.dumps(body).encode(), "application/json")
    return [t["token"] for t in response.get("tokens", [])] if status == 200 else None


def same_analysis(c, es, user_index, reference_index, texts, message, **target):
    """Compare analysis output of the user's index with a reference index, text by text."""
    for text in texts:
        got = analyze(es, user_index, text, **target)
        want = analyze(es, reference_index, text, **target)
        if got != want:
            return c.fail(message, f"for {text!r}: expected {want}, got {got}")
    return c.check(True, message)


def temp_copy(es, source, name):
    """Create an empty index with the settings and mappings of `source`, to test its behavior safely.
    Returns an error message, or None."""
    status, settings = es.send("GET", f"/{source}/_settings?flat_settings=true")
    if status != 200:
        return f"can't read index {source}"
    settings = next(iter(settings.values()))["settings"]
    keep = {k: v for k, v in settings.items()
            if k.startswith(("index.analysis.", "index.mapping.", "index.sort.", "index.number_of_shards"))}
    mappings = next(iter(es.get(f"/{source}/_mapping").values()))["mappings"]
    status, response = es.send("PUT", f"/{name}", json.dumps({"settings": keep, "mappings": mappings}).encode(),
                               "application/json")
    return None if status == 200 else short_error(response)


def index_settings(es, index):
    status, response = es.send("GET", f"/{index}/_settings?flat_settings=true")
    if status != 200:
        return None
    return next(iter(response.values()))["settings"]


# --- Comparing query results ---------------------------------------------------

def _round(value):
    return float(f"{value:.6g}") if isinstance(value, float) else value


def same_hits(c, answer, reference, ordered):
    ids = lambda r: [(h["_index"], h["_id"]) for h in get(r, "hits.hits", [])]
    got, want = ids(answer), ids(reference)
    if ordered:
        return c.check(got == want, "returns the expected documents in the expected order",
                       _hits_detail(got, want))
    return c.check(sorted(got) == sorted(want), "returns the expected documents",
                   _hits_detail(got, want))


def same_scores(c, answer, reference):
    """Scores equal within a small relative tolerance, so equivalent query forms pass."""
    scores = lambda r: [h.get("_score") or 0.0 for h in get(r, "hits.hits", [])]
    got, want = scores(answer), scores(reference)
    close = len(got) == len(want) and all(abs(g - w) <= 1e-4 * max(1.0, abs(w)) for g, w in zip(got, want))
    detail = None
    if not close and got and want:
        detail = f"first hit: expected score {want[0]:.4f}, got {got[0]:.4f}"
    return c.check(close, "the scores are computed as requested", detail)


def _hits_detail(got, want):
    missing = [doc_id for index, doc_id in want if (index, doc_id) not in got]
    extra = [doc_id for index, doc_id in got if (index, doc_id) not in want]
    parts = [f"expected {len(want)} hits, got {len(got)}"]
    if missing:
        parts.append(f"missing ids: {', '.join(missing[:5])}{' ...' if len(missing) > 5 else ''}")
    if extra:
        parts.append(f"unexpected ids: {', '.join(extra[:5])}{' ...' if len(extra) > 5 else ''}")
    if not missing and not extra and len(got) == len(want):
        parts.append("same documents, different order")
    return "; ".join(parts)


def canonical_aggs(aggs):
    """Aggregation results without the names the user chose, so any naming passes."""
    def one(agg):
        if "buckets" in agg:
            buckets = agg["buckets"]
            if isinstance(buckets, dict):   # keyed buckets (filters, keyed ranges)
                buckets = [dict(b, key=k) for k, b in buckets.items()]
            return ("buckets", [(_bucket_id(b), b.get("doc_count"), children(b)) for b in buckets])
        if "hits" in agg and isinstance(agg["hits"], dict):
            return ("hits", [h.get("_id") for h in agg["hits"].get("hits", [])])
        return ("metric", sorted(_leaves(agg)))

    def children(obj):
        kids = [one(v) for k, v in obj.items() if isinstance(v, dict) and k not in ("key", "meta")]
        return sorted(kids, key=repr)

    return children(aggs or {})


def _bucket_id(bucket):
    # Range buckets are identified by their bounds, so user-chosen labels don't matter
    if "from" in bucket or "to" in bucket:
        return ("range", _round(bucket.get("from")), _round(bucket.get("to")))
    return _canon_key(bucket.get("key"))


def _canon_key(key):
    if isinstance(key, dict):
        return tuple(sorted(key.items()))
    if isinstance(key, list):
        return tuple(key)
    return _round(key)


def _leaves(obj, prefix=""):
    for k, v in obj.items():
        if k in ("meta", "value_as_string") or k.endswith("_as_string"):
            continue
        if isinstance(v, dict):
            yield from _leaves(v, f"{prefix}{k}.")
        elif isinstance(v, (int, float)) or v is None:
            yield (f"{prefix}{k}", _round(v))


def same_aggs(c, answer, reference):
    got, want = canonical_aggs(get(answer, "aggregations")), canonical_aggs(get(reference, "aggregations"))
    if not got:
        return c.fail("returns the expected aggregation results", "the response has no aggregations")
    return c.check(got == want, "returns the expected aggregation results",
                   "the aggregation results differ from the reference solution "
                   "(check the buckets, their order, and the metric values)")


def same_esql(c, answer, reference):
    rows = lambda r: [[_round(v) for v in row] for row in get(r, "values", [])]
    got, want = rows(answer), rows(reference)
    if get(answer, "columns") is None:
        return c.fail("returns the expected rows", "the answer is not an ES|QL response (POST _query)")
    names = lambda r: [col["name"] for col in get(r, "columns", [])]
    c.equal(names(answer), names(reference), "returns the expected columns, in order")
    return c.check(got == want, "returns the expected rows",
                   f"expected {len(want)} rows, got {len(got)}" if len(got) != len(want)
                   else "the values or their order differ from the reference solution")


# --- Cleanup -----------------------------------------------------------------

def cleanup_resources(es, iid):
    """Delete everything on a cluster whose name contains the instance ID."""
    match = lambda name: iid in name
    def names(path, extract):
        status, response = es.send("GET", path)
        return [n for n in extract(response) if match(n)] if status == 200 and response else []

    status, resolved = es.send("GET", f"/_resolve/index/*{iid}*?expand_wildcards=all")
    if status == 200:
        for ds in resolved.get("data_streams", []):
            es.send("DELETE", f"/_data_stream/{ds['name']}")
        for alias in resolved.get("aliases", []):
            for index in alias.get("indices", []):
                es.send("DELETE", f"/{index}/_alias/{alias['name']}")
        backing = {i for ds in resolved.get("data_streams", []) for i in ds.get("backing_indices", [])}
        for index in resolved.get("indices", []):
            if index["name"] not in backing:
                es.send("DELETE", f"/{index['name']}")
    for name in names("/_index_template", lambda r: [t["name"] for t in r.get("index_templates", [])]):
        es.send("DELETE", f"/_index_template/{name}")
    for name in names("/_component_template", lambda r: [t["name"] for t in r.get("component_templates", [])]):
        es.send("DELETE", f"/_component_template/{name}")
    for name in names("/_ingest/pipeline", lambda r: r.keys()):
        es.send("DELETE", f"/_ingest/pipeline/{name}")
    for name in names("/_ilm/policy", lambda r: r.keys()):
        es.send("DELETE", f"/_ilm/policy/{name}")
    for name in names("/_slm/policy", lambda r: r.keys()):
        es.send("DELETE", f"/_slm/policy/{name}")
    for name in names("/_enrich/policy", lambda r: [p["config"][next(iter(p["config"]))]["name"]
                                                     for p in r.get("policies", [])]):
        es.send("DELETE", f"/_enrich/policy/{name}")
    for name in names("/_cluster/state/metadata?filter_path=metadata.stored_scripts",
                      lambda r: get(r, "metadata.stored_scripts", {}).keys()):
        es.send("DELETE", f"/_scripts/{name}")
    for name in names("/_security/role", lambda r: r.keys()):
        es.send("DELETE", f"/_security/role/{name}")
    for name in names("/_security/user", lambda r: r.keys()):
        es.send("DELETE", f"/_security/user/{name}")
    for name in names("/_snapshot", lambda r: r.keys()):
        es.send("DELETE", f"/_snapshot/{name}")
    for name in names("/_synonyms", lambda r: [s["synonyms_set"] for s in r.get("results", [])]):
        es.send("DELETE", f"/_synonyms/{name}")
