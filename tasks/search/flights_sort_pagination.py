from lib.sampledata import FLIGHT_COUNTRIES, FLIGHTS
from lib.tasklib import Task


class FlightsSortPagination(Task):
    id = "search-flights-sort-pagination"
    title = "Sort on several fields and fetch a later page"
    covers = ["search.results.sort", "search.results.from-size", "search.results.search-after",
              "search.term.term"]
    answer = "query"
    compare = "hits_ordered"

    def params(self, rnd, iid):
        return {"country": rnd.choice(FLIGHT_COUNTRIES), "page": rnd.choice([3, 4, 5, 6]),
                "per_page": rnd.choice([10, 20, 25])}

    def prompt(self, ctx):
        p = ctx.p
        first = (p["page"] - 1) * p["per_page"] + 1
        return f"""
In `{FLIGHTS}`, list the flights to {p['country']} (DestCountry) sorted by ticket price
(AvgTicketPrice), most expensive first; flights with the same price are sorted by flight
number (FlightNum), A to Z.

The application shows {p['per_page']} flights per page. Return page {p['page']}: results {first} to
{first + p['per_page'] - 1}, in that order.

Bonus: do it with search_after instead of from, as you would for deep pagination. Your
answer can contain several requests; the last one is graded.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {FLIGHTS}/_search
{{
  "from": {(p['page'] - 1) * p['per_page']},
  "size": {p['per_page']},
  "query": {{
    "term": {{ "DestCountry": "{p['country']}" }}
  }},
  "sort": [
    {{ "AvgTicketPrice": "desc" }},
    {{ "FlightNum": "asc" }}
  ]
}}
"""

    def wrong_answer(self, ctx):
        # Off by one page
        p = ctx.p
        return self.solution(ctx).replace(f'"from": {(p["page"] - 1) * p["per_page"]}',
                                          f'"from": {p["page"] * p["per_page"]}')
