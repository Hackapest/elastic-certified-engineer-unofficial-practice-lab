import json

from lib.sampledata import ALL_CATEGORIES, ECOMMERCE
from lib.tasklib import Task, get


class EcommerceTemplateConditionals(Task):
    id = "search-ecommerce-template-conditionals"
    title = "Search template with optional clauses and a list parameter (conditionals, toJson)"
    covers = ["search.templates.template-defaults", "search.templates.search-template", "search.templates.render",
              "search.templates.msearch-template", "search.term.terms"]
    answer = "state"

    def params(self, rnd, iid):
        return {"id": f"order-finder-{iid}", "size": rnd.choice([10, 20, 25]),
                "sort": rnd.choice(["order_date", "taxful_total_price"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create a stored search template `{p['id']}` for `{ECOMMERCE}` that returns {p['size']} orders,
sorted by {p['sort']} descending, and accepts these parameters:

  categories   a LIST of category names, e.g. ["Men's Shoes", "Women's Shoes"]; only orders
               containing at least one of them (category.keyword). Required.
  text         optional: if given, the order's product names (products.product_name) must
               match this text (a match query). If not given, there is no text condition at all.
  min_total    optional: if given, only orders whose taxful_total_price is at least this.
               If not given, no price condition at all.

Test it with the render API, with and without the optional parameters. Bonus: run two
variants at once with the multi search template API.
"""

    def query(self, p, categories, text=None, min_total=None):
        filters = [{"terms": {"category.keyword": categories}}]
        if min_total is not None:
            filters.append({"range": {"taxful_total_price": {"gte": min_total}}})
        must = [{"match": {"products.product_name": text}}] if text else []
        return {"size": p["size"], "sort": [{p["sort"]: "desc"}],
                "query": {"bool": {"must": must, "filter": filters}}}

    def solution(self, ctx):
        p = ctx.p
        source = ('{"size": ' + str(p["size"]) + ', "sort": [{"' + p["sort"] + '": "desc"}], '
                  '"query": {"bool": { '
                  '{{#text}}"must": [{"match": {"products.product_name": "{{text}}"}}],{{/text}}'
                  '"filter": [{"terms": {"category.keyword": {{#toJson}}categories{{/toJson}} }}'
                  '{{#min_total}}, {"range": {"taxful_total_price": {"gte": {{min_total}} } } }{{/min_total}}'
                  ']}}}')
        return f"""
PUT _scripts/{p['id']}
{{
  "script": {{
    "lang": "mustache",
    "source": {json.dumps(source)}
  }}
}}

# Test:
# GET _render/template
# {{ "id": "{p['id']}", "params": {{ "categories": ["Men's Shoes"], "min_total": 50 }} }}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, _ = es.send("GET", f"/_scripts/{p['id']}")
        if not c.check(status == 200, f"stored template {p['id']} exists"):
            return
        cases = [
            ("with only categories", {"categories": ALL_CATEGORIES[:2]}),
            ("with categories and text", {"categories": [ALL_CATEGORIES[3]], "text": "black boots"}),
            ("with categories and min_total", {"categories": ALL_CATEGORIES[2:5], "min_total": 80}),
            ("with all parameters", {"categories": [ALL_CATEGORIES[1], ALL_CATEGORIES[4]], "text": "dress",
                                     "min_total": 60}),
        ]
        for label, params in cases:
            status, got = es.send("POST", f"/{ECOMMERCE}/_search/template",
                                  json.dumps({"id": p["id"], "params": params}).encode(), "application/json")
            if status != 200:
                c.fail(f"returns the right orders {label}", f"params {params}: HTTP {status}: "
                       f"{get(got, 'error.root_cause.0.reason', get(got, 'error.reason', got))}")
                continue
            want = es.post(f"/{ECOMMERCE}/_search", self.query(p, **params))
            ids = lambda r: [h["_id"] for h in get(r, "hits.hits", [])]
            c.check(ids(got) == ids(want), f"returns the right orders {label}",
                    f"params {params}: expected {len(ids(want))} orders, got {len(ids(got))}"
                    + ("" if len(ids(got)) != len(ids(want)) else " (different orders or order)"))
