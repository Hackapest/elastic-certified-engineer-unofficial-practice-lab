import random

from lib.tasklib import Task
from tasks.ingest._common import check_against_reference, render_pipeline

HOSTS = ["shop.example.co.uk", "api.eu.example.com", "www.example.org", "static.cdn.example.net",
         "example.com.au", "m.store.example.de"]
PATHS = ["/search%20results/item.php", "/v1/users", "/cat%C3%A9gorie/chaussures.html", "/img/logo%202x.png",
         "/", "/docs/getting%20started.pdf"]
QUERIES = ["", "?q=red%20shoes&page=2", "?lang=fr", "?id=42&sort=price%20desc"]
FRAGMENTS = ["", "#top", "#reviews"]
AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "curl/8.4.0",
]


def request(rnd):
    scheme = rnd.choice(["http", "https"])
    port = rnd.choice(["", ":8443", ":8080"])
    return {"request_url": f"{scheme}://{rnd.choice(HOSTS)}{port}{rnd.choice(PATHS)}{rnd.choice(QUERIES)}"
                           f"{rnd.choice(FRAGMENTS)}",
            "agent": rnd.choice(AGENTS)}


class WebPipeline(Task):
    id = "ingest-web-pipeline"
    title = "Break URLs and user agents into fields (uri_parts, urldecode, registered_domain, user_agent)"
    covers = ["ingest.pipelines.processor.uri_parts", "ingest.pipelines.processor.urldecode",
              "ingest.pipelines.processor.registered_domain", "ingest.pipelines.processor.user_agent",
              "ingest.pipelines.processor.remove", "ingest.pipelines.simulate"]

    def params(self, rnd, iid):
        return {"pipeline": f"web-requests-{iid}", "ua_field": rnd.choice(["user_agent", "client.agent"]),
                "examples": [request(rnd) for _ in range(2)]}

    def processors(self, p):
        return [
            {"uri_parts": {"field": "request_url", "target_field": "url"}},
            {"urldecode": {"field": "url.path"}},
            {"urldecode": {"field": "url.query", "ignore_missing": True}},
            {"registered_domain": {"field": "url.domain", "target_field": "url"}},
            {"user_agent": {"field": "agent", "target_field": p["ua_field"]}},
            {"remove": {"field": ["request_url", "agent"]}},
        ]

    def prompt(self, ctx):
        p, ua = ctx.p, ctx.p["ua_field"]
        examples = "\n".join(f'  {{ "request_url": "{e["request_url"]}",\n    "agent": "{e["agent"]}" }}'
                             for e in p["examples"])
        return f"""
Web requests arrive with a URL-encoded `request_url` and the raw `agent` header:

{examples}

Create an ingest pipeline `{p['pipeline']}` that sets:

  url.scheme, url.domain, url.port, url.path, url.query, url.fragment, url.extension
      the parts of request_url; url.path and url.query must be URL-decoded
      (e.g. "/search results/item.php", "q=red shoes&page=2")
  url.registered_domain, url.subdomain, url.top_level_domain
      e.g. for shop.example.co.uk: "example.co.uk", "shop", "co.uk"
  {ua}.name, {ua}.version, {ua}.os.name, {ua}.device.name
      parsed from agent (e.g. "Chrome", "120.0.0.0", "Windows", "Other")

Parts that are absent from a URL (no port, no query, ...) must simply be absent, without errors.
Finally remove request_url and agent.
"""

    def solution(self, ctx):
        return render_pipeline(ctx.p["pipeline"], self.processors(ctx.p))

    def verify(self, ctx, c):
        p, ua = ctx.p, ctx.p["ua_field"]
        rnd = random.Random()
        docs = [request(rnd) for _ in range(10)]
        checks = [(f"url.{f} is set as requested", f"url.{f}")
                  for f in ("scheme", "domain", "port", "path", "query", "fragment", "extension",
                            "registered_domain", "subdomain", "top_level_domain")]
        checks += [(f"{ua}.{f} is set as requested", f"{ua}.{f}") for f in ("name", "version", "os.name",
                                                                           "device.name")]
        checks.append(("request_url and agent are removed",
                       lambda r: ("request_url" in r["source"], "agent" in r["source"])))
        check_against_reference(c, ctx.es, p["pipeline"], self.processors(p), docs, checks)
