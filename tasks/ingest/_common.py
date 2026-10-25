"""Helpers shared by the ingest templates (not a template: files starting with _ are skipped)."""

import json

from lib.tasklib import get, short_error

MISSING = object()


def send(es, method, path, body=None):
    """JSON request that never raises: (status, response)."""
    data = None if body is None else json.dumps(body).encode()
    return es.send(method, path, data=data, content_type="application/json" if data else None)


def bulk(es, index, docs, refresh=True, ids=None):
    """Index docs (list of dicts) with the bulk API. ids: optional list of _id values."""
    lines = []
    for n, doc in enumerate(docs):
        action = {"_index": index}
        if ids is not None:
            action["_id"] = str(ids[n])
        lines.append(json.dumps({"index": action}))
        lines.append(json.dumps(doc))
    status, response = es.send("POST", f"/_bulk?refresh={'true' if refresh else 'false'}",
                               data=("\n".join(lines) + "\n").encode(), content_type="application/x-ndjson")
    if status != 200 or response.get("errors"):
        raise RuntimeError(f"bulk indexing into {index} failed: {str(response)[:500]}")
    return response


def simulate(es, docs, pipeline=None, processors=None):
    """Simulate a stored pipeline (by name) or an inline list of processors.
    Returns (results, error). Each result is {"source": ..., "index": ..., "error": ..., "dropped": bool}."""
    body = {"docs": [{"_index": d.get("_index", "test"), "_source": d["_source"]} if "_source" in d
                     else {"_source": d} for d in docs]}
    if pipeline:
        status, response = send(es, "POST", f"/_ingest/pipeline/{pipeline}/_simulate", body)
    else:
        body["pipeline"] = processors if isinstance(processors, dict) else {"processors": processors}
        status, response = send(es, "POST", "/_ingest/pipeline/_simulate", body)
    if status != 200:
        return None, short_error(response)
    results = []
    for doc in response.get("docs", []):
        if doc is None or (isinstance(doc, dict) and doc.get("doc") is None and "error" not in doc):
            results.append({"dropped": True, "source": None, "index": None, "error": None})
        elif "error" in doc:
            err = doc["error"]
            results.append({"dropped": False, "source": None, "index": None,
                            "error": f"{err.get('type')}: {err.get('reason')}"})
        else:
            results.append({"dropped": False, "source": get(doc, "doc._source", {}),
                            "index": get(doc, "doc._index"), "error": None,
                            "meta": get(doc, "doc", {})})
    return results, None


def pipeline_exists(c, es, name):
    status, _ = es.send("GET", f"/_ingest/pipeline/{name}")
    return c.check(status == 200, f"pipeline {name} exists")


def field(source, path):
    """Value at a dotted path, or MISSING. Also accepts flat keys with dots ("a.b": 1)."""
    if source is None:
        return MISSING
    if path in source:
        return source[path]
    node = source
    parts = path.split(".")
    for i, part in enumerate(parts):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, dict) and ".".join(parts[i:]) in node:
            return node[".".join(parts[i:])]
        else:
            return MISSING
    return node


def show(value):
    return "(missing)" if value is MISSING else repr(value)


def compare_outputs(c, label_inputs, got, want, checks):
    """Compare simulate results of the user's pipeline (got) with expected results (want).

    checks: list of (message, fn) where fn(result) returns the compared value; or
            (message, path) to compare a source field.
    want: list of results in the same shape as simulate() returns (or built by hand).
    Adds one check per message (first difference as detail), plus one for errors/drops."""
    problems = {}
    for label, g, w in zip(label_inputs, got, want):
        if w["error"] is None and g["error"] is not None:
            problems.setdefault("_errors", f"for {label}: {g['error']}")
            continue
        if g["dropped"] != w["dropped"]:
            problems.setdefault("_dropped", f"for {label}: expected the document to be "
                                f"{'dropped' if w['dropped'] else 'kept'}")
            continue
        if bool(g["error"]) != bool(w["error"]):
            problems.setdefault("_failed", f"for {label}: expected the document to "
                                f"{'fail' if w['error'] else 'be processed without error'}"
                                f"{', found ' + str(g['error']) if g['error'] else ''}")
            continue
        if w["dropped"] or w["error"]:
            continue
        for message, how in checks:
            fn = how if callable(how) else (lambda r, path=how: field(r["source"], path))
            gv, wv = fn(g), fn(w)
            if gv != wv:
                problems.setdefault(message, f"for {label}: expected {show(wv)}, found {show(gv)}")
    c.check("_errors" not in problems, "the pipeline processes the test documents without unexpected errors",
            problems.get("_errors"))
    if any(w["dropped"] for w in want) or any(g["dropped"] for g in got):
        c.check("_dropped" not in problems, "the right documents are dropped", problems.get("_dropped"))
    if any(w["error"] for w in want) or "_failed" in problems:
        c.check("_failed" not in problems, "the right documents fail", problems.get("_failed"))
    for message, _ in checks:
        c.check(message not in problems, message, problems.get(message))


def kibana(ctx):
    k = ctx.kibana()
    k.headers["elastic-api-version"] = "2023-10-31"
    return k


def render_pipeline(name, processors, extra=None):
    body = {"processors": processors}
    if extra:
        body.update(extra)
    return f"PUT _ingest/pipeline/{name}\n{json.dumps(body, indent=2)}\n"


def check_against_reference(c, es, pipeline, processors, docs, checks, labels=None):
    """Simulate the user's pipeline and the reference processors on the same docs and compare."""
    if not pipeline_exists(c, es, pipeline):
        return
    got, error = simulate(es, docs, pipeline=pipeline)
    if not c.check(error is None, "the pipeline can be simulated", error):
        return
    want, error = simulate(es, docs, processors=processors)
    if error:
        raise RuntimeError(f"reference pipeline failed: {error}")
    labels = labels or [json.dumps(d.get("_source", d))[:200] for d in docs]
    compare_outputs(c, labels, got, want, checks)
