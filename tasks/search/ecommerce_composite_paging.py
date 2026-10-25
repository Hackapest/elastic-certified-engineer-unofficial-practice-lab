import json

from lib.sampledata import ECOMMERCE
from lib.tasklib import Task, get


class EcommerceCompositePaging(Task):
    id = "search-ecommerce-composite-paging"
    title = "Page through all bucket combinations (composite aggregation, after_key)"
    covers = ["search.bucket-aggs.composite", "search.metric-aggs.sum", "search.aggs.sub-aggregations"]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"page_size": rnd.choice([5, 8, 10]), "page": rnd.choice([2, 3]),
                "second": rnd.choice(["category.keyword", "geoip.continent_name"]),
                "day_order": rnd.choice(["asc", "desc"])}

    def body(self, p, after=None):
        comp = {"size": p["page_size"],
                "sources": [{"day": {"terms": {"field": "day_of_week", "order": p["day_order"]}}},
                            {"group": {"terms": {"field": p["second"]}}}]}
        if after:
            comp["after"] = after
        return {"size": 0, "aggs": {"combos": {"composite": comp,
                                               "aggs": {"revenue": {"sum": {"field": "taxful_total_price"}}}}}}

    def prompt(self, ctx):
        p = ctx.p
        order = "A to Z" if p["day_order"] == "asc" else "Z to A"
        return f"""
A nightly export must read every combination of weekday and {p['second']} in `{ECOMMERCE}`, with the
total revenue (sum of taxful_total_price) of each combination, a page at a time.

Use a composite aggregation with two sources, named exactly "day" (day_of_week, sorted {order})
and "group" ({p['second']}, sorted A to Z), and pages of {p['page_size']} combinations.

Hand in the requests you run to get to page {p['page']}; the last request must return exactly page
{p['page']} (the combinations {(p['page'] - 1) * p['page_size'] + 1} to {p['page'] * p['page_size']}). No hits.
"""

    def solution(self, ctx):
        p = ctx.p
        requests, after = [], None
        for page in range(1, p["page"] + 1):
            body = self.body(p, after)
            requests.append(f"# page {page}\nGET {ECOMMERCE}/_search\n{json.dumps(body, indent=2)}\n")
            after = get(ctx.es.post(f"/{ECOMMERCE}/_search", body), "aggregations.combos.after_key")
        return "\n".join(requests) + "\n# take \"after_key\" from each response and pass it as \"after\" in the next request\n"

    def wrong_answer(self, ctx):
        # Stops at the first page
        return f"GET {ECOMMERCE}/_search\n{json.dumps(self.body(ctx.p))}\n"
