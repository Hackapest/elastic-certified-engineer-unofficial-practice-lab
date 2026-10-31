import json

from lib.sampledata import ECOMMERCE, PRODUCT_WORDS
from lib.tasklib import Task, get, same_hits


class ProductsTemplateExam(Task):
    id = "search-products-template-exam"
    title = "Exam-style: a search template with a nested query, pagination, highlighting and sorting"
    covers = ["search.templates.search-template", "search.templates.template-defaults", "search.joining.nested",
              "search.joining.inner-hits", "search.results.highlight", "search.results.sort", "search.results.from-size"]
    size = "exam"
    answer = "state"

    def params(self, rnd, iid):
        words = rnd.sample(PRODUCT_WORDS, 2)
        return {"index": f"catalog-orders-{iid}", "id": f"products-{iid}", "size": rnd.choice([20, 25, 30]),
                "tag": rnd.choice(["mark", "strong", "em"]), "words": words}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/{p['index']}", {"mappings": {"properties": {
            "order_id": {"type": "keyword"},
            "geoip": {"properties": {"continent_name": {"type": "keyword"}, "city_name": {"type": "keyword"}}},
            "products": {"type": "nested", "properties": {"product_name": {"type": "text"},
                                                          "price": {"type": "float"}}}}}})
        es.post("/_reindex?refresh=true", {
            "source": {"index": ECOMMERCE, "_source": ["order_id", "geoip.continent_name", "geoip.city_name",
                                                       "products.product_name", "products.price"]},
            "dest": {"index": p["index"]}}, timeout=120)

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create the stored search template `{p['id']}` for a shop search on `{p['index']}`, where products is
nested. It takes these parameters:

  product   the search term, required
  from      the result to start at; default 0
  size      the page size; default {p['size']}

It must:
  - run a match query for the search term on products.product_name, through a nested query
  - wrap the matching words in products.product_name in <{p['tag']}> and </{p['tag']}> in the results
  - sort by geoip.continent_name, then geoip.city_name, then relevance score, all descending

Test it: search for "{p['words'][0]}" with the defaults, then fetch the second page.
"""

    def template(self, p):
        return ('{"from": {{from}}{{^from}}0{{/from}}, "size": {{size}}{{^size}}' + str(p["size"]) + '{{/size}}, '
                '"query": {"nested": {"path": "products", '
                '"query": {"match": {"products.product_name": "{{product}}"}}, '
                '"inner_hits": {"highlight": {"pre_tags": ["<' + p["tag"] + '>"], "post_tags": ["</' + p["tag"] + '>"], '
                '"fields": {"products.product_name": {}}}}}}, '
                '"sort": [{"geoip.continent_name": "desc"}, {"geoip.city_name": "desc"}, {"_score": "desc"}]}')

    def solution(self, ctx):
        p = ctx.p
        return f"""
# A nested field is highlighted through inner_hits of the nested query.
PUT _scripts/{p['id']}
{{
  "script": {{
    "lang": "mustache",
    "source": {json.dumps(self.template(p))}
  }}
}}

POST {p['index']}/_search/template
{{
  "id": "{p['id']}",
  "params": {{ "product": "{p['words'][0]}" }}
}}
"""

    def reference(self, es, p, word, start, size):
        return es.post(f"/{p['index']}/_search", {
            "from": start, "size": size, "_source": False,
            "query": {"nested": {"path": "products", "query": {"match": {"products.product_name": word}}}},
            "sort": [{"geoip.continent_name": "desc"}, {"geoip.city_name": "desc"}, {"_score": "desc"}]})

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        if not c.check(es.send("GET", f"/_scripts/{p['id']}")[0] == 200, f"stored template {p['id']} exists"):
            return
        cases = [("with the defaults", {"product": p["words"][0]}, p["words"][0], 0, p["size"]),
                 ("for a later page", {"product": p["words"][1], "from": 5, "size": 3}, p["words"][1], 5, 3)]
        for label, params, word, start, size in cases:
            status, got = es.send("POST", f"/{p['index']}/_search/template",
                                  json.dumps({"id": p["id"], "params": params}).encode(), "application/json")
            if not c.check(status == 200, f"the template runs {label}", f"HTTP {status}: {str(got)[:300]}"):
                continue
            same_hits(c, got, self.reference(es, p, word, start, size), ordered=True)
            c.check(f"<{p['tag']}>" in json.dumps(get(got, "hits.hits", [])).lower(),
                    f"the matching words are wrapped in <{p['tag']}> tags {label}")
