import json

from lib.sampledata import ALL_CATEGORIES, ECOMMERCE
from lib.tasklib import Task, get


class EcommerceSearchTemplate(Task):
    id = "search-ecommerce-search-template"
    title = "Stored search template with parameters and defaults"
    covers = ["search.templates.search-template", "search.templates.template-defaults", "search.templates.render",
              "search.term.term", "search.term.range", "search.results.sort"]
    answer = "state"

    def params(self, rnd, iid):
        return {"id": f"orders-by-category-{iid}", "default_size": rnd.choice([5, 10, 15]),
                "default_min": rnd.choice([0, 20, 50])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create a stored search template with the ID `{p['id']}` that searches `{ECOMMERCE}` for orders
in a given category, newest first (order_date). It takes these parameters:

  category    exact category name (category.keyword), required
  min_price   only orders whose taxful_total_price is at least this; default {p['default_min']}
  size        number of orders to return; default {p['default_size']}

Test it with the render API and by running it, e.g. with only "category" given.
"""

    def query(self, category, min_price, size):
        return {"size": size, "sort": [{"order_date": "desc"}],
                "query": {"bool": {"filter": [{"term": {"category.keyword": category}},
                                              {"range": {"taxful_total_price": {"gte": min_price}}}]}}}

    def solution(self, ctx):
        p = ctx.p
        source = ('{"size": {{size}}{{^size}}' + str(p["default_size"]) + '{{/size}}, '
                  '"sort": [{"order_date": "desc"}], '
                  '"query": {"bool": {"filter": ['
                  '{"term": {"category.keyword": "{{category}}"}}, '
                  '{"range": {"taxful_total_price": {"gte": {{min_price}}{{^min_price}}' + str(p["default_min"]) +
                  '{{/min_price}}}}}]}}}')
        return f"""
PUT _scripts/{p['id']}
{{
  "script": {{
    "lang": "mustache",
    "source": {json.dumps(source)}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = es.send("GET", f"/_scripts/{p['id']}")
        if not c.check(status == 200, f"stored template {p['id']} exists"):
            return
        cases = [
            ("with all parameters", {"category": ALL_CATEGORIES[1], "min_price": 70, "size": 7},
             (ALL_CATEGORIES[1], 70, 7)),
            ("with only category (defaults apply)", {"category": ALL_CATEGORIES[4]},
             (ALL_CATEGORIES[4], p["default_min"], p["default_size"])),
            ("with category and size", {"category": ALL_CATEGORIES[2], "size": 3},
             (ALL_CATEGORIES[2], p["default_min"], 3)),
        ]
        for label, params, expected in cases:
            status, got = es.send("POST", f"/{ECOMMERCE}/_search/template",
                                  json.dumps({"id": p["id"], "params": params}).encode(), "application/json")
            if status != 200:
                c.fail(f"returns the right orders {label}", f"HTTP {status}: {get(got, 'error.reason', got)}")
                continue
            want = es.post(f"/{ECOMMERCE}/_search", self.query(*expected))
            ids = lambda r: [h["_id"] for h in get(r, "hits.hits", [])]
            c.check(ids(got) == ids(want), f"returns the right orders {label}",
                    f"params {params}: expected {len(ids(want))} orders, got {len(ids(got))}"
                    + ("" if len(ids(got)) != len(ids(want)) else " (different orders or order)"))
