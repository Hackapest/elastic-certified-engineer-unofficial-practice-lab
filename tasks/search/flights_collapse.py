from lib.sampledata import FLIGHTS
from lib.tasklib import Task

ORIGINS = ["IT", "US", "JP", "CN", "CA", "DE", "IN", "AU", "GB"]


class FlightsCollapse(Task):
    id = "search-flights-collapse"
    title = "One result per group (collapse with inner_hits)"
    covers = ["search.results.collapse", "search.results.sort", "search.term.term"]
    answer = "query"
    compare = "hits_ordered"

    def params(self, rnd, iid):
        return {"origin": rnd.choice(ORIGINS), "group": rnd.choice(["DestCountry", "Carrier", "DestWeather"]),
                "order": rnd.choice(["cheapest", "most expensive"]), "inner": rnd.choice([2, 3])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
A travel site lists flights from `{FLIGHTS}` departing from the country "{p['origin']}"
(OriginCountry). It wants exactly ONE result per {p['group']} value: the {p['order']} flight
(AvgTicketPrice) of that group, and the groups ordered by that price ({p['order']} first).

Return all groups in one response (there are fewer than 100). Do it with a search request that
returns hits (not an aggregation). Bonus: also return, inside each hit, the {p['inner']}
{p['order']} flights of its group.
"""

    def solution(self, ctx):
        p = ctx.p
        order = "asc" if p["order"] == "cheapest" else "desc"
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 100,
  "query": {{ "term": {{ "OriginCountry": "{p['origin']}" }} }},
  "sort": [ {{ "AvgTicketPrice": "{order}" }} ],
  "collapse": {{
    "field": "{p['group']}",
    "inner_hits": {{
      "name": "top_flights",
      "size": {p['inner']},
      "sort": [ {{ "AvgTicketPrice": "{order}" }} ]
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Without collapse: just the overall cheapest/most expensive flights
        p = ctx.p
        order = "asc" if p["order"] == "cheapest" else "desc"
        return f"""
GET {FLIGHTS}/_search
{{
  "size": 100,
  "query": {{ "term": {{ "OriginCountry": "{p['origin']}" }} }},
  "sort": [ {{ "AvgTicketPrice": "{order}" }} ]
}}
"""
