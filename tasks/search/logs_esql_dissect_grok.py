from lib.sampledata import LOGS
from lib.tasklib import Task

QUERY = r'''
    FROM kibana_sample_data_logs
    | DISSECT message "%{clientip} - - [%{logged_at}] \"%{method} %{path} HTTP/%{http_version}\" %{status} %{size} %{rest}"
    | WHERE status == "$STATUS"
    | GROK path "^/%{WORD:product}/.*\\.%{WORD:filetype}$"
    | WHERE filetype IS NOT NULL
    | EVAL size = TO_INTEGER(size)
    | STATS requests = COUNT(*), total_bytes = SUM(size) BY product, filetype
    | SORT $SORT DESC, product, filetype
    | KEEP product, filetype, requests, total_bytes
    | LIMIT $TOP
'''


class LogsEsqlDissectGrok(Task):
    id = "search-logs-esql-dissect-grok"
    title = "Parse raw log lines in ES|QL (DISSECT, GROK)"
    covers = ["search.esql.command.dissect", "search.esql.command.grok", "search.esql.dissect-grok-esql",
              "search.esql.command.limit", "search.esql.functions.type-conversion", "search.esql.command.stats"]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        return {"status": rnd.choice(["200", "404", "503"]), "sort": rnd.choice(["requests", "total_bytes"]),
                "top": rnd.choice([3, 5, 8])}

    def query(self, p):
        return QUERY.replace("$STATUS", p["status"]).replace("$SORT", p["sort"]).replace("$TOP", str(p["top"]))

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Pretend `{LOGS}` only had the raw access log line in the field message, e.g.:

  187.212.218.89 - - [2018-09-03T05:12:56.084Z] "GET /elasticsearch/elasticsearch-6.3.2.zip HTTP/1.1" 200 8941 "-" "Mozilla/5.0 ..."

(the fields after the request line are the HTTP status and the response size in bytes). Write an
ES|QL query that takes everything it needs from message only (not from the other fields):

  - only requests with status {p['status']};
  - only requests for a file below a product directory, i.e. paths like "/<product>/.../<name>.<filetype>",
    such as "/elasticsearch/elasticsearch-6.3.2.zip" (product "elasticsearch", filetype "zip") or
    "/beats/filebeat/filebeat-6.3.2-linux-x86.tar.gz" (product "beats", filetype "gz", the text after
    the last dot);
  - per product and filetype: requests (the number of requests) and total_bytes (the sum of the
    response sizes, as a number).

Columns in this order: product, filetype, requests, total_bytes. Sorted by {p['sort']} (highest first),
then product and filetype (A to Z); only the first {p['top']} rows.
"""

    def solution(self, ctx):
        return f'''
POST _query
{{
  "query": """{self.query(ctx.p)}"""
}}
'''

    def wrong_answer(self, ctx):
        # Forgets the status condition
        return self.solution(ctx).replace(f'| WHERE status == "{ctx.p["status"]}"\n', "")
