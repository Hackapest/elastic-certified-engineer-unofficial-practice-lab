import json
import random

from lib.tasklib import Task, get, index_settings
from tasks.ingest._common import send

CATEGORIES = ["Garden", "TOYS", "Books", "KitChen", "Sports"]


class DefaultFinalPipeline(Task):
    id = "ingest-default-final-pipeline"
    title = "Default and final pipelines, and overriding the pipeline per request"
    covers = ["ingest.pipelines.default-final", "ingest.pipelines.use-on-request",
              "ingest.pipelines.metadata-access", "ingest.methods.bulk", "ingest.pipelines.processor.set",
              "ingest.pipelines.processor.lowercase"]

    def params(self, rnd, iid):
        return {"index": f"items-{iid}", "default": f"items-default-{iid}", "final": f"items-final-{iid}",
                "import": f"items-import-{iid}", "field": rnd.choice(["origin", "source_system"]),
                "skus": [f"SKU-{rnd.randint(100, 999)}-{n}" for n in range(3)],
                "cats": rnd.sample(CATEGORIES, 3)}

    def prompt(self, ctx):
        p, f = ctx.p, ctx.p["field"]
        return f"""
Create three ingest pipelines:

  {p['default']}   sets {f} to "manual" and lowercases the field `category`
  {p['import']}    sets {f} to "import"
  {p['final']}     sets `ingested_at` to the ingest timestamp and `stored_in` to the name of the
                   index the document is written to (read both from the document's metadata)

Create an index `{p['index']}` that runs `{p['default']}` for documents indexed without naming
a pipeline, and runs `{p['final']}` for every document, whatever pipeline was used before.

Then, with ONE bulk request, index into `{p['index']}`:
  - {{ "sku": "{p['skus'][0]}", "category": "{p['cats'][0]}" }} and
    {{ "sku": "{p['skus'][1]}", "category": "{p['cats'][1]}" }} through `{p['import']}` (instead of the default pipeline)
  - {{ "sku": "{p['skus'][2]}", "category": "{p['cats'][2]}" }} with the default pipeline
"""

    def solution(self, ctx):
        p, f = ctx.p, ctx.p["field"]
        return f"""
PUT _ingest/pipeline/{p['default']}
{{
  "processors": [
    {{ "set": {{ "field": "{f}", "value": "manual" }} }},
    {{ "lowercase": {{ "field": "category" }} }}
  ]
}}

PUT _ingest/pipeline/{p['import']}
{{
  "processors": [
    {{ "set": {{ "field": "{f}", "value": "import" }} }}
  ]
}}

PUT _ingest/pipeline/{p['final']}
{{
  "processors": [
    {{ "set": {{ "field": "ingested_at", "value": "{{{{{{_ingest.timestamp}}}}}}" }} }},
    {{ "set": {{ "field": "stored_in", "value": "{{{{{{_index}}}}}}" }} }}
  ]
}}

PUT {p['index']}
{{
  "settings": {{
    "index.default_pipeline": "{p['default']}",
    "index.final_pipeline": "{p['final']}"
  }}
}}

POST _bulk?refresh=true
{{ "index": {{ "_index": "{p['index']}", "pipeline": "{p['import']}" }} }}
{json.dumps({"sku": p['skus'][0], "category": p['cats'][0]})}
{{ "index": {{ "_index": "{p['index']}", "pipeline": "{p['import']}" }} }}
{json.dumps({"sku": p['skus'][1], "category": p['cats'][1]})}
{{ "index": {{ "_index": "{p['index']}" }} }}
{json.dumps({"sku": p['skus'][2], "category": p['cats'][2]})}
"""

    def verify(self, ctx, c):
        p, es, f = ctx.p, ctx.es, ctx.p["field"]
        for name in ("default", "import", "final"):
            status, _ = send(es, "GET", f"/_ingest/pipeline/{p[name]}")
            c.check(status == 200, f"pipeline {p[name]} exists")
        settings = index_settings(es, p["index"])
        if not c.check(settings is not None, f"index {p['index']} exists"):
            return
        c.equal(settings.get("index.default_pipeline"), p["default"], "the default pipeline is set")
        c.equal(settings.get("index.final_pipeline"), p["final"], "the final pipeline is set")

        def simulated(pipeline=None):
            doc = {"sku": "X-1", "category": random.choice(CATEGORIES)}
            path = f"/_ingest/{p['index']}/_simulate" + (f"?pipeline={pipeline}" if pipeline else "")
            status, response = send(es, "POST", path, {"docs": [{"_source": doc}]})
            return doc, get(response, "docs.0.doc._source", {}) if status == 200 else {}

        doc, src = simulated()
        c.check(src.get(f) == "manual" and src.get("category") == doc["category"].lower(),
                "a document indexed without a pipeline goes through the default pipeline",
                f"{f}={src.get(f)!r}, category={src.get('category')!r}")
        final_ok = lambda s: str(s.get("ingested_at", ""))[:2] == "20" and s.get("stored_in") == p["index"]
        c.check(final_ok(src), "the final pipeline sets ingested_at and stored_in",
                f"ingested_at={src.get('ingested_at')!r}, stored_in={src.get('stored_in')!r}")
        doc, src = simulated(p["import"])
        c.check(src.get(f) == "import" and final_ok(src),
                f"a document indexed with ?pipeline={p['import']} goes through it and then the final pipeline",
                f"{f}={src.get(f)!r}, stored_in={src.get('stored_in')!r}")

        status, response = send(es, "GET", f"/{p['index']}/_search", {"size": 20})
        by_sku = {get(h, "_source.sku"): h["_source"] for h in get(response, "hits.hits", [])} if status == 200 else {}
        expected = {p["skus"][0]: ("import", p["cats"][0]), p["skus"][1]: ("import", p["cats"][1]),
                    p["skus"][2]: ("manual", p["cats"][2].lower())}
        bad = None
        for sku, (origin, cat) in expected.items():
            s = by_sku.get(sku)
            if s is None:
                bad = bad or f"{sku} is not in the index"
            elif (s.get(f), s.get("category"), final_ok(s)) != (origin, cat, True):
                bad = bad or f"{sku}: {f}={s.get(f)!r}, category={s.get('category')!r}, stored_in={s.get('stored_in')!r}"
        c.check(bad is None and len(by_sku) == 3, "the three documents are indexed through the right pipelines",
                bad or f"found {len(by_sku)} documents")
