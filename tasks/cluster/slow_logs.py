import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cluster_helpers as h  # noqa: E402

from lib.tasklib import Task, get, index_settings  # noqa: E402


class SlowLogs(Task):
    id = "cluster-slow-logs"
    title = "Configure search and indexing slow logs on an index and for future indices"
    covers = ["cluster.health.slow-logs"]
    answer = "state"

    def params(self, rnd, iid):
        return {"index": f"catalog-{iid}", "template": f"catalog-{iid}", "pattern": f"catalog-{iid}-*",
                "query_warn": rnd.choice(["2s", "5s", "10s"]), "query_info": rnd.choice(["500ms", "800ms", "1s"]),
                "fetch_warn": rnd.choice(["200ms", "500ms", "1s"]), "index_warn": rnd.choice(["2s", "3s", "5s"]),
                "source": rnd.choice([100, 500, 2000]), "user": rnd.choice([True, False])}

    def setup(self, ctx):
        h.bulk(ctx.es, ctx.p["index"], h.sales_docs(ctx.iid, "a", 20), h.SALES_MAPPING)

    def expected(self, p):
        e = {
            "index.search.slowlog.threshold.query.warn": h.duration_ms(p["query_warn"]),
            "index.search.slowlog.threshold.query.info": h.duration_ms(p["query_info"]),
            "index.search.slowlog.threshold.fetch.warn": h.duration_ms(p["fetch_warn"]),
            "index.indexing.slowlog.threshold.index.warn": h.duration_ms(p["index_warn"]),
            "index.indexing.slowlog.source": str(p["source"]),
        }
        if p["user"]:
            e["index.search.slowlog.include.user"] = "true"
        return e

    def actual(self, settings, p):
        got = {}
        for key in self.expected(p):
            value = settings.get(key)
            got[key] = h.duration_ms(value) if "threshold" in key else (None if value is None else str(value))
        return got

    def prompt(self, ctx):
        p = ctx.p
        user = ("\n  - search slow log entries include the user who ran the search" if p["user"] else "")
        return f"""
Users complain that searches on `{ctx.p['index']}` on cluster A are sometimes slow. Configure
slow logs on that index:

  - search queries slower than {p['query_warn']} are logged at WARN level, slower than
    {p['query_info']} at INFO level
  - search fetch phases slower than {p['fetch_warn']} are logged at WARN level
  - indexing operations slower than {p['index_warn']} are logged at WARN level, with the first
    {p['source']} characters of the document source{user}

New indices matching `{p['pattern']}` must get the same slow log settings automatically:
create the index template `{p['template']}` for them.
"""

    def solution(self, ctx):
        p = ctx.p
        user = ',\n    "index.search.slowlog.include.user": true' if p["user"] else ""
        settings = f"""{{
    "index.search.slowlog.threshold.query.warn": "{p['query_warn']}",
    "index.search.slowlog.threshold.query.info": "{p['query_info']}",
    "index.search.slowlog.threshold.fetch.warn": "{p['fetch_warn']}",
    "index.indexing.slowlog.threshold.index.warn": "{p['index_warn']}",
    "index.indexing.slowlog.source": {p['source']}{user}
  }}"""
        return f"""
PUT {p['index']}/_settings
{settings}

PUT _index_template/{p['template']}
{{
  "index_patterns": ["{p['pattern']}"],
  "template": {{
    "settings": {settings}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        want = self.expected(p)
        settings = index_settings(es, p["index"]) or {}
        c.equal(self.actual(settings, p), want, f"{p['index']} has the slow log settings")
        sim = h.send(es, "POST", f"/_index_template/_simulate_index/catalog-{ctx.iid}-2027")[1] or {}
        flat = {}

        def flatten(prefix, obj):
            for k, v in obj.items():
                if isinstance(v, dict):
                    flatten(f"{prefix}{k}.", v)
                else:
                    flat[f"{prefix}{k}"] = v
        flatten("", get(sim, "template.settings", {}) or {})
        c.equal(self.actual(flat, p), want, f"new {p['pattern']} indices get the slow log settings")

    def cleanup(self, ctx):
        h.full_cleanup(ctx.iid)
