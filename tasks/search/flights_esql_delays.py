from lib.tasklib import Task

INDEX = "kibana_sample_data_flights"
WEATHER = ["Rain", "Clear", "Sunny", "Cloudy", "Heavy Fog", "Thunder & Lightning", "Damaging Wind", "Hail"]


class FlightsEsqlDelays(Task):
    id = "search-flights-esql-delays"
    title = "Average delay per carrier with ES|QL"
    covers = [
        "search.esql.rest", "search.esql.command.from", "search.esql.command.where",
        "search.esql.command.stats", "search.esql.command.eval", "search.esql.command.sort",
        "search.esql.command.keep", "search.esql.functions.aggregation", "search.esql.functions.math",
    ]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        return {"weather": rnd.choice(WEATHER), "decimals": rnd.choice([1, 2])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Write an ES|QL query on `{INDEX}` that looks only at flights that were not cancelled and
whose destination weather (DestWeather) was "{p['weather']}".

For each carrier, return:

  Carrier     the carrier
  flights     the number of such flights
  avg_delay   the average FlightDelayMin, rounded to {p['decimals']} decimal(s)

Return exactly these three columns in this order, one row per carrier, sorted by avg_delay
from highest to lowest. Run it with the _query API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f'''
POST _query
{{
  "query": """
    FROM {INDEX}
    | WHERE Cancelled == false AND DestWeather == "{p['weather']}"
    | STATS flights = COUNT(*), avg_delay = AVG(FlightDelayMin) BY Carrier
    | EVAL avg_delay = ROUND(avg_delay, {p['decimals']})
    | SORT avg_delay DESC
    | KEEP Carrier, flights, avg_delay
  """
}}
'''

    def wrong_answer(self, ctx):
        # Forgets to exclude cancelled flights
        return self.solution(ctx).replace("Cancelled == false AND ", "")
