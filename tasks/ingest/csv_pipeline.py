import json
import random

from lib.tasklib import Task, get
from tasks.ingest._common import check_against_reference, render_pipeline, send

CITIES = ["Berlin", "Lyon", "Porto", "Gdansk", "Malmo", "Bergamo", "Ghent"]
# (prompt wording, date_rounding, index_name_format, python strftime)
ROUNDINGS = [("month", "M", "yyyy.MM", "%Y.%m"), ("day", "d", "yyyy.MM.dd", "%Y.%m.%d"),
             ("year", "y", "yyyy", "%Y")]
# (example, java format, python strftime)
DATE_FORMATS = [("dd/MM/yyyy", "%d/%m/%Y"), ("MM-dd-yyyy", "%m-%d-%Y"), ("yyyy.MM.dd", "%Y.%m.%d")]


def row(rnd, sep, fmt):
    import datetime
    day = datetime.date(2025, 1, 1) + datetime.timedelta(days=rnd.randrange(600))
    city = rnd.choice(CITIES)
    if rnd.random() < 0.3:
        city = f'"{city}, DE"' if sep == "," else f"{city}, DE"
    return {"day": day, "line": sep.join([day.strftime(fmt), f"ORD-{rnd.randint(1000, 9999)}", city,
                                          str(rnd.randint(1, 20)), f"{rnd.randint(1, 500)}.{rnd.randint(0, 99):02d}"])}


class CsvPipeline(Task):
    id = "ingest-csv-pipeline"
    title = "Split CSV lines into typed fields and route them to monthly indices (csv, convert, date_index_name)"
    covers = ["ingest.pipelines.processor.csv", "ingest.pipelines.processor.convert",
              "ingest.pipelines.processor.date", "ingest.pipelines.processor.date_index_name",
              "ingest.pipelines.processor.remove", "ingest.pipelines.use-on-request"]

    def params(self, rnd, iid):
        r = rnd.choice(ROUNDINGS)
        f = rnd.choice(DATE_FORMATS)
        sep = rnd.choice([",", ";"])
        return {"pipeline": f"orders-csv-{iid}", "prefix": f"orders-{iid}-", "sep": sep,
                "rounding": list(r), "date_format": list(f),
                "examples": [row(rnd, sep, f[1])["line"] for _ in range(2)]}

    def processors(self, p):
        csv = {"field": "line", "target_fields": ["order_date", "order_id", "city", "quantity", "price"]}
        if p["sep"] != ",":
            csv["separator"] = p["sep"]
        return [
            {"csv": csv},
            {"convert": {"field": "quantity", "type": "integer"}},
            {"convert": {"field": "price", "type": "double"}},
            {"date": {"field": "order_date", "formats": [p["date_format"][0]], "target_field": "order_date",
                      "output_format": "yyyy-MM-dd"}},
            {"date_index_name": {"field": "order_date", "date_formats": ["yyyy-MM-dd"],
                                 "index_name_prefix": p["prefix"], "date_rounding": p["rounding"][1],
                                 "index_name_format": p["rounding"][2]}},
            {"remove": {"field": "line"}},
        ]

    def prompt(self, ctx):
        p = ctx.p
        examples = "\n".join(f'  {{ "line": {json.dumps(e)} }}' for e in p["examples"])
        example_index = p["prefix"] + {"M": "2025.07", "d": "2025.07.14", "y": "2025"}[p["rounding"][1]]
        return f"""
Order exports arrive as documents with one field `line`, a CSV row separated by `{p['sep']}`
(values containing the separator are quoted), for example:

{examples}

The columns are: order date ({p['date_format'][0]}), order id, city, quantity, price.

Create an ingest pipeline `{p['pipeline']}` that:

  - splits the row into the fields order_date, order_id, city, quantity and price
  - makes quantity an integer and price a double
  - rewrites order_date in the format yyyy-MM-dd (e.g. 2025-07-14)
  - sends each document to one index per {p['rounding'][0]} of its order date, named
    `{p['prefix']}<date>` with the date formatted as {p['rounding'][2]} (e.g. {example_index})
  - removes `line`

Then index the two example documents with a single bulk request that uses the pipeline (the bulk
request names any index; the pipeline decides where the documents go).
"""

    def solution(self, ctx):
        p = ctx.p
        bulk = "\n".join(f'{{ "index": {{ "_index": "orders-incoming-{ctx.iid}" }} }}\n{json.dumps({"line": e})}'
                         for e in p["examples"])
        return render_pipeline(p["pipeline"], self.processors(p)) + \
            f"\nPOST _bulk?pipeline={p['pipeline']}&refresh=true\n{bulk}\n"

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        rnd = random.Random()
        rows = [row(rnd, p["sep"], p["date_format"][1]) for _ in range(6)]
        docs = [{"line": r["line"]} for r in rows]
        checks = [(f"{f} is extracted as requested", f) for f in ("order_date", "order_id", "city", "quantity",
                                                                    "price")]
        checks.append(("line is removed", "line"))
        check_against_reference(c, es, p["pipeline"], self.processors(p), docs, checks)
        if not c.passed:
            return
        # Where do documents really go? Index fresh rows and look at the target index.
        lines = []
        for d in docs:
            lines += [json.dumps({"index": {"_index": f"orders-check-{ctx.iid}"}}), json.dumps(d)]
        status, response = es.send("POST", f"/_bulk?pipeline={p['pipeline']}",
                                   data=("\n".join(lines) + "\n").encode(), content_type="application/x-ndjson")
        wrong = None
        for r, item in zip(rows, get(response, "items", [])):
            item = item.get("index", {})
            want = p["prefix"] + r["day"].strftime(p["rounding"][3])
            if item.get("_index") != want and wrong is None:
                wrong = f"for {r['line']!r}: expected index {want}, the document went to {item.get('_index')}"
            if item.get("_id"):
                send(es, "DELETE", f"/{item.get('_index')}/_doc/{item['_id']}")
        c.check(status == 200 and wrong is None, "documents go to the right index for their order date",
                wrong or str(response)[:300])
        # The two example documents
        status, response = send(es, "GET", f"/{p['prefix']}*/_search", {"query": {"bool": {"should": [
            {"match_phrase": {"order_id": e.split(p["sep"])[1]}} for e in p["examples"]]}}})
        found = get(response, "hits.total.value", 0) if status == 200 else 0
        c.check(found >= 2, "the two example documents were indexed through the pipeline",
                f"found {found} of them in {p['prefix']}*")
