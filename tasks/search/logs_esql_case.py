from lib.sampledata import LOG_EXTENSIONS, LOGS
from lib.tasklib import Task


class LogsEsqlCase(Task):
    id = "search-logs-esql-case"
    title = "Classify and count with ES|QL (CASE, STATS by two columns)"
    covers = ["search.esql.functions.conditional", "search.esql.command.eval", "search.esql.command.stats",
              "search.esql.command.where", "search.esql.command.sort", "search.esql.command.keep",
              "search.esql.functions.aggregation", "search.esql.functions.math"]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        return {"extension": rnd.choice(LOG_EXTENSIONS), "metric": rnd.choice(["bytes", "machine.ram"])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Write an ES|QL query on `{LOGS}` for requests of files with the extension "{p['extension']}"
(extension.keyword). Classify each request by its response code (response.keyword):

  "200" -> ok,  "404" -> not_found,  anything else -> error

and return one row per operating system (machine.os.keyword) and class, with these columns
in this order:

  os         the operating system
  class      ok, not_found or error
  requests   the number of requests
  avg_value  the average {p['metric']}, rounded to a whole number

Sorted by os, then class (both A to Z). Run it with the _query API.
"""

    def solution(self, ctx):
        p = ctx.p
        return f'''
POST _query
{{
  "query": """
    FROM {LOGS}
    | WHERE extension.keyword == "{p['extension']}"
    | EVAL class = CASE(response.keyword == "200", "ok", response.keyword == "404", "not_found", "error")
    | STATS requests = COUNT(*), avg_value = ROUND(AVG({p['metric']})) BY os = machine.os.keyword, class
    | SORT os, class
    | KEEP os, class, requests, avg_value
  """
}}
'''

    def wrong_answer(self, ctx):
        # Treats 404 as an error
        return self.solution(ctx).replace('response.keyword == "404", "not_found", ', "")
