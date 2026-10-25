"""The exam curriculum as a tree: domain -> topic -> entry.

Entries are either hands-on (features practised through tasks) or reading items
(concepts, ticked off by the user). The data lives in taxonomy/<domain>.py and
is built with the helpers below; entry IDs are `domain.topic.entry`.
"""

import importlib
from dataclasses import dataclass, field

CORE, COMMON, EXTENDED = "core", "common", "extended"
LEVELS = (CORE, COMMON, EXTENDED)
HANDS_ON, READING = "hands-on", "reading"
REQUIREMENTS = ("shell", "ml", "kibana", "cluster-b")

DOMAIN_MODULES = ("architecture", "data", "ingest", "search", "cluster", "security")

DOCS = "https://www.elastic.co/docs/"


@dataclass
class Entry:
    id: str
    title: str
    kind: str
    level: str
    docs: list
    requires: tuple = ()
    note: str = ""
    full_id: str = ""


@dataclass
class Topic:
    id: str
    title: str
    entries: list
    full_id: str = ""


@dataclass
class Domain:
    id: str
    title: str
    topics: list = field(default_factory=list)


# --- Builders used by the taxonomy/ data files -------------------------------

def H(id, title, *docs, level=COMMON, requires=(), note=""):
    """A hands-on entry: a feature practised through tasks."""
    return Entry(id, title, HANDS_ON, level, list(docs), _tuple(requires), note)


def R(id, title, *docs, level=COMMON, note=""):
    """A reading entry: conceptual, ticked off by the user."""
    return Entry(id, title, READING, level, list(docs), (), note)


def topic(id, title, entries):
    return Topic(id, title, entries)


def domain(id, title, topics):
    return Domain(id, title, topics)


def _tuple(value):
    return (value,) if isinstance(value, str) else tuple(value)


# --- Doc URL helpers ---------------------------------------------------------

def doc(path):
    return DOCS + path


def query_doc(slug):
    return doc(f"reference/query-languages/query-dsl/query-dsl-{slug}")


def agg_doc(slug):
    return doc(f"reference/aggregations/search-aggregations-{slug}")


def processor_doc(slug):
    return doc(f"reference/ingest-processor/{slug}")


def mapping_doc(slug):
    return doc(f"reference/elasticsearch/mapping-reference/{slug}")


def analysis_doc(slug):
    return doc(f"reference/text-analysis/analysis-{slug}")


def esql_doc(slug):
    return doc(f"reference/query-languages/esql/{slug}")


def ilm_doc(slug):
    return doc(f"reference/elasticsearch/index-lifecycle-actions/ilm-{slug}")


def api_doc(operation):
    return doc(f"api/doc/elasticsearch/operation/operation-{operation}")


# --- Loading and validation --------------------------------------------------

def load():
    domains = []
    for name in DOMAIN_MODULES:
        d = importlib.import_module(f"taxonomy.{name}").DOMAIN
        for t in d.topics:
            t.full_id = f"{d.id}.{t.id}"
            for e in t.entries:
                e.full_id = f"{t.full_id}.{e.id}"
        domains.append(d)
    return domains


def entries(domains):
    return [e for d in domains for t in d.topics for e in t.entries]


def check_links(domains, workers=16):
    """Fetch every distinct doc URL; return problems for those that don't resolve."""
    from concurrent.futures import ThreadPoolExecutor
    import urllib.error
    import urllib.request

    users = {}
    for e in entries(domains):
        for url in e.docs:
            users.setdefault(url, []).append(e.full_id)

    def status(url):
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ece-taxonomy-check"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code
        except OSError as e:
            return str(e)

    print(f"Checking {len(users)} doc links...", flush=True)
    with ThreadPoolExecutor(workers) as pool:
        results = dict(zip(users, pool.map(status, users)))
    return [f"{url} -> {code} (used by {', '.join(users[url])})"
            for url, code in sorted(results.items()) if code != 200]


def validate(domains):
    """Return a list of problems with the taxonomy data (empty if fine)."""
    problems = []
    seen = set()
    for e in entries(domains):
        if e.full_id in seen:
            problems.append(f"duplicate id {e.full_id}")
        seen.add(e.full_id)
        if e.level not in LEVELS:
            problems.append(f"{e.full_id}: unknown level {e.level}")
        if not e.docs:
            problems.append(f"{e.full_id}: no doc links")
        for r in e.requires:
            if r not in REQUIREMENTS:
                problems.append(f"{e.full_id}: unknown requirement {r}")
        for url in e.docs:
            if not url.startswith(DOCS):
                problems.append(f"{e.full_id}: link outside elastic.co/docs: {url}")
    return problems
