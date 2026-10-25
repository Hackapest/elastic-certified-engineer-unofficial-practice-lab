from lib.sampledata import FLIGHT_CARRIERS, FLIGHTS, ECOMMERCE, ALL_CATEGORIES
from lib.tasklib import Task, get


class FlightsMsearch(Task):
    id = "search-flights-msearch"
    title = "Several searches in one request (multi search)"
    covers = ["search.templates.msearch", "search.results.sort", "search.term.term"]
    answer = "query"

    def params(self, rnd, iid):
        return {"carrier": rnd.choice(FLIGHT_CARRIERS), "n_flights": rnd.choice([3, 5, 7]),
                "category": rnd.choice(ALL_CATEGORIES), "n_orders": rnd.choice([3, 4, 6]),
                "flight_sort": rnd.choice(["FlightDelayMin", "AvgTicketPrice", "DistanceKilometers"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
A start page needs two result lists, and must fetch them with ONE request (the multi search API):

  1. from `{FLIGHTS}`: the {p['n_flights']} flights of the carrier "{p['carrier']}" (Carrier) with the
     highest {p['flight_sort']}, highest first;
  2. from `{ECOMMERCE}`: the {p['n_orders']} most recent orders (order_date) that contain the category
     "{p['category']}" (category.keyword), newest first.

The responses must come back in this order (flights first).
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET _msearch
{{ "index": "{FLIGHTS}" }}
{{ "size": {p['n_flights']}, "query": {{ "term": {{ "Carrier": "{p['carrier']}" }} }}, "sort": [ {{ "{p['flight_sort']}": "desc" }} ] }}
{{ "index": "{ECOMMERCE}" }}
{{ "size": {p['n_orders']}, "query": {{ "term": {{ "category.keyword": "{p['category']}" }} }}, "sort": [ {{ "order_date": "desc" }} ] }}
"""

    def grade(self, ctx, c, answer, reference):
        responses = get(answer, "responses")
        if not c.check(isinstance(responses, list), "the answer is a multi search response",
                       "use GET _msearch with one header line and one body line per search"):
            return
        want = reference["responses"]
        if not c.equal(len(responses), len(want), "returns two responses"):
            return
        ids = lambda r: [h["_id"] for h in get(r, "hits.hits", [])]
        for label, g, w in zip(["the flights", "the orders"], responses, want):
            c.check(ids(g) == ids(w), f"returns {label} in the expected order",
                    get(g, "error.reason") or f"expected {len(ids(w))} hits, got {len(ids(g))}"
                    + ("" if len(ids(g)) != len(ids(w)) else " (different hits or order)"))

    def wrong_answer(self, ctx):
        # Lowest first instead of highest first
        return self.solution(ctx).replace(f'"{ctx.p["flight_sort"]}": "desc"', f'"{ctx.p["flight_sort"]}": "asc"')
