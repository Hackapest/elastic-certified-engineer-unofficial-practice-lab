from lib.sampledata import LOG_EXTENSIONS, LOGS
from lib.tasklib import Task


class LogsEsqlParamsBucket(Task):
    id = "search-logs-esql-params-bucket"
    title = "Weekly traffic with query parameters, BUCKET and string functions (ES|QL)"
    covers = ["search.esql.params", "search.esql.functions.grouping", "search.esql.functions.string",
              "search.esql.functions.date-time", "search.esql.command.keep", "search.esql.command.sort"]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        return {"ext": rnd.choice(LOG_EXTENSIONS), "min_bytes": rnd.choice([1000, 3000, 5000, 8000]),
                "interval": rnd.choice(["1 week", "1 day"])}

    def prompt(self, ctx):
        p = ctx.p
        unit = "week" if p["interval"] == "1 week" else "day"
        return f"""
Write an ES|QL query on `{LOGS}` for requests of files with the extension "{p['ext']}" (extension.keyword)
and at least {p['min_bytes']} bytes (bytes). The extension and the byte threshold must not be written
into the query text: pass them as named query parameters (?ext and ?min_bytes) in the request.

Return one row per {unit} (@timestamp, the {unit} it falls in, as the start of that {unit}) and operating
system, with these columns in this order:

  {unit:<6}         the start of the {unit} (a date)
  os             machine.os.keyword in upper case, with spaces replaced by underscores ("win xp" -> "WIN_XP")
  requests       the number of requests
  total_bytes    the sum of bytes

Sorted by {unit} (oldest first), then os (A to Z).
"""

    def solution(self, ctx):
        p = ctx.p
        unit = "week" if p["interval"] == "1 week" else "day"
        return f'''
POST _query
{{
  "query": """
    FROM {LOGS}
    | WHERE extension.keyword == ?ext AND bytes >= ?min_bytes
    | EVAL os = TO_UPPER(REPLACE(machine.os.keyword, " ", "_"))
    | STATS requests = COUNT(*), total_bytes = SUM(bytes) BY {unit} = BUCKET(@timestamp, {p['interval']}), os
    | SORT {unit}, os
    | KEEP {unit}, os, requests, total_bytes
  """,
  "params": [ {{ "ext": "{p['ext']}" }}, {{ "min_bytes": {p['min_bytes']} }} ]
}}
'''

    def wrong_answer(self, ctx):
        # Upper case without replacing the spaces
        return self.solution(ctx).replace('TO_UPPER(REPLACE(machine.os.keyword, " ", "_"))', "TO_UPPER(machine.os.keyword)")
