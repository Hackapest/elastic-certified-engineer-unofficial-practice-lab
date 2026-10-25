from lib.tasklib import Task


class EsqlRow(Task):
    id = "search-esql-row"
    title = "Try ES|QL functions on literal values with ROW"
    covers = ["search.esql.command.row", "search.esql.command.eval", "search.esql.functions.string",
              "search.esql.functions.date-time", "search.esql.functions.type-conversion"]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        return {"email": rnd.choice(["Anna.Meyer@Example.COM", "ben.okafor@shop.example", "Chloe_Rossi@Mail.example"]),
                "date": rnd.choice(["2026-03-15T08:30:00Z", "2025-12-31T23:59:00Z", "2026-07-04T12:00:00Z"]),
                "number": rnd.choice(["42", "1337", "7"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Before writing ES|QL against real data, you can test functions on literal values. Write one ES|QL
query that starts with ROW and returns exactly one row with these columns, in this order:

  email     the literal "{p['email']}"
  domain    the part of email after the "@", in lower case
  date      the literal "{p['date']}" converted to a date
  month     the month of that date (1-12), as an integer
  doubled   the literal string "{p['number']}" converted to an integer and multiplied by 2

Run it with the _query API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f'''
POST _query
{{
  "query": """
    ROW email = "{p['email']}", date = TO_DATETIME("{p['date']}"), number = "{p['number']}"
    | EVAL domain = TO_LOWER(SPLIT(email, "@")), month = DATE_EXTRACT("month_of_year", date),
           doubled = TO_INTEGER(number) * 2
    | EVAL domain = MV_LAST(domain)
    | KEEP email, domain, date, month, doubled
  """
}}
'''

    def wrong_answer(self, ctx):
        # The day of the month instead of the month
        return self.solution(ctx).replace('"month_of_year"', '"day_of_month"')
