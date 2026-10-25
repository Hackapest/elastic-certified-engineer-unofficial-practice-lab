from lib.sampledata import LOGS
from lib.tasklib import Task

BLOCKS = ["0.0.0.0/4", "16.0.0.0/4", "32.0.0.0/4", "48.0.0.0/4", "64.0.0.0/4", "80.0.0.0/4", "96.0.0.0/4",
          "112.0.0.0/4", "128.0.0.0/4", "144.0.0.0/4", "160.0.0.0/4", "176.0.0.0/4", "192.0.0.0/4"]


class LogsEsqlIp(Task):
    id = "search-logs-esql-ip"
    title = "Failed requests per subnet (ES|QL CIDR_MATCH, IP_PREFIX, TO_INTEGER)"
    covers = ["search.esql.functions.ip", "search.esql.functions.type-conversion", "search.esql.functions.aggregation",
              "search.esql.command.where", "search.esql.command.limit"]
    answer = "query"
    compare = "esql"

    def params(self, rnd, iid):
        return {"blocks": sorted(rnd.sample(BLOCKS, 2), key=BLOCKS.index), "min_status": rnd.choice([400, 500]),
                "top": rnd.choice([5, 10])}

    def prompt(self, ctx):
        p = ctx.p
        a, b = p["blocks"]
        return f"""
Security wants to know which /8 subnets (the first byte of the IP address, e.g. 23.0.0.0) inside the
networks {a} and {b} produce failing requests in `{LOGS}`.

The HTTP status is stored as text in response.keyword: convert it to a number and only keep requests
with status {p['min_status']} or higher, from clients (clientip) in either network. Return, with ES|QL,
one row per /8 subnet with these columns in this order:

  subnet     the /8 subnet address, as an IP (e.g. 23.0.0.0)
  requests   the number of such requests
  clients    the number of distinct client IPs

Sorted by requests (highest first), then subnet (lowest first); only the first {p['top']} rows.
"""

    def solution(self, ctx):
        p = ctx.p
        a, b = p["blocks"]
        return f'''
POST _query
{{
  "query": """
    FROM {LOGS}
    | WHERE CIDR_MATCH(clientip, "{a}", "{b}") AND TO_INTEGER(response.keyword) >= {p['min_status']}
    | EVAL subnet = IP_PREFIX(clientip, 8, 0)
    | STATS requests = COUNT(*), clients = COUNT_DISTINCT(clientip) BY subnet
    | SORT requests DESC, subnet
    | LIMIT {p['top']}
  """
}}
'''

    def wrong_answer(self, ctx):
        # /16 subnets instead of /8
        return self.solution(ctx).replace("IP_PREFIX(clientip, 8, 0)", "IP_PREFIX(clientip, 16, 0)")
