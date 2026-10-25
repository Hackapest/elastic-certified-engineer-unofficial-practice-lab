from lib.sampledata import CONTINENTS, ECOMMERCE, ALL_CATEGORIES
from lib.tasklib import Task, get

REGIONS = {"eu": "Europe", "na": "North America", "asia": "Asia", "africa": "Africa"}


class SalesCountMultiIndex(Task):
    id = "search-sales-count-multi-index"
    title = "Count matching documents across several indices (count API, multi-target syntax)"
    covers = ["search.basics.count", "search.basics.multi-index"]
    answer = "query"

    def params(self, rnd, iid):
        regions = list(REGIONS)
        rnd.shuffle(regions)
        return {"prefix": f"sales-{iid}", "wanted": sorted(regions[:2]), "category": rnd.choice(ALL_CATEGORIES),
                "min_total": rnd.choice([40, 60, 80, 100])}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for region, continent in REGIONS.items():
            es.post("/_reindex?refresh=true", {
                "source": {"index": ECOMMERCE, "query": {"term": {"geoip.continent_name": continent}}},
                "dest": {"index": f"{p['prefix']}-{region}"}}, timeout=120)
        # An archive index that a careless wildcard would also count
        es.post("/_reindex?refresh=true", {"source": {"index": ECOMMERCE},
                                           "dest": {"index": f"{p['prefix']}-archive"}}, timeout=120)

    def prompt(self, ctx):
        p = ctx.p
        names = " and ".join(f"`{p['prefix']}-{r}`" for r in p["wanted"])
        return f"""
eCommerce orders have been split into one index per region: `{p['prefix']}-eu`, `-na`, `-asia`,
`-africa`, plus `{p['prefix']}-archive` holding a copy of everything.

Using the count API (the response must be a count, not hits), count the orders in {names}
together, in one request, that contain the category "{p['category']}" (category.keyword) and
whose taxful_total_price is greater than {p['min_total']}.
"""

    def solution(self, ctx):
        p = ctx.p
        indices = ",".join(f"{p['prefix']}-{r}" for r in p["wanted"])
        return f"""
GET {indices}/_count
{{
  "query": {{
    "bool": {{
      "filter": [
        {{ "term": {{ "category.keyword": "{p['category']}" }} }},
        {{ "range": {{ "taxful_total_price": {{ "gt": {p['min_total']} }} }} }}
      ]
    }}
  }}
}}
"""

    def grade(self, ctx, c, answer, reference):
        if not c.check(isinstance(answer, dict) and "count" in answer, "the answer is a count API response",
                       "use GET <indices>/_count"):
            return
        c.equal(answer["count"], reference["count"], "counts the expected orders")
        c.check(reference["count"] > 0, "the reference count is not zero (template sanity check)")

    def wrong_answer(self, ctx):
        # A wildcard over all regions also counts the archive and the other regions
        indices = ",".join(f"{ctx.p['prefix']}-{r}" for r in ctx.p["wanted"])
        return self.solution(ctx).replace(f"GET {indices}/_count", f"GET {ctx.p['prefix']}-*/_count")
