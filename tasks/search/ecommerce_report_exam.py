import json

from lib.sampledata import CONTINENTS, ECOMMERCE, PRODUCT_WORDS
from lib.tasklib import Task, get, same_aggs, same_hits

FIELDS = ["order_id", "order_date", "customer_full_name", "taxful_total_price"]


class EcommerceReportExam(Task):
    id = "search-ecommerce-report-exam"
    title = "Exam-style: one search request with query, sorting, highlighting and aggregations"
    covers = ["search.compound.bool", "search.fulltext.match", "search.term.range", "search.results.sort",
              "search.results.source-filtering", "search.results.highlight", "search.bucket-aggs.terms",
              "search.metric-aggs.sum", "search.pipeline-aggs.max-bucket", "search.aggs.sub-aggregations"]
    size = "exam"
    answer = "query"

    def params(self, rnd, iid):
        return {"continent": rnd.choice(CONTINENTS), "word": rnd.choice(PRODUCT_WORDS),
                "min_price": rnd.choice([40, 60, 80]), "size": rnd.choice([10, 20])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Build one search request on `{ECOMMERCE}` for a report about orders from {p['continent']}
(geoip.continent_name) that contain a product with "{p['word']}" in its name
(products.product_name) and cost at least {p['min_price']} (taxful_total_price, inclusive).
The continent and price conditions must not affect scoring.

  - Return the {p['size']} most expensive of these orders, most expensive first; orders with the
    same price sorted by order_date, newest first.
  - Return only these source fields: {', '.join(FIELDS)}
  - Highlight the matched words in products.product_name (default highlight tags).
  - Also return, over all matching orders: the revenue (sum of taxful_total_price) per day of
    the week (day_of_week, all 7 days), and which day has the highest revenue, with a
    pipeline aggregation.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": {p['size']},
  "_source": {json.dumps(FIELDS)},
  "query": {{
    "bool": {{
      "must": [
        {{ "match": {{ "products.product_name": "{p['word']}" }} }}
      ],
      "filter": [
        {{ "term": {{ "geoip.continent_name": "{p['continent']}" }} }},
        {{ "range": {{ "taxful_total_price": {{ "gte": {p['min_price']} }} }} }}
      ]
    }}
  }},
  "sort": [
    {{ "taxful_total_price": "desc" }},
    {{ "order_date": "desc" }}
  ],
  "highlight": {{
    "fields": {{ "products.product_name": {{}} }}
  }},
  "aggs": {{
    "per_day": {{
      "terms": {{ "field": "day_of_week", "size": 7 }},
      "aggs": {{
        "revenue": {{ "sum": {{ "field": "taxful_total_price" }} }}
      }}
    }},
    "best_day": {{
      "max_bucket": {{ "buckets_path": "per_day>revenue" }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Sorted cheapest first
        return self.solution(ctx).replace('{ "taxful_total_price": "desc" }', '{ "taxful_total_price": "asc" }')

    def grade(self, ctx, c, answer, reference):
        same_hits(c, answer, reference, ordered=True)
        hits = get(answer, "hits.hits", [])
        fields = {f for h in hits for f in h.get("_source", {})}
        c.check(hits and fields == set(FIELDS), "only the requested source fields are returned",
                f"fields returned: {sorted(fields)}")
        got = [h.get("highlight") for h in hits]
        want = [h.get("highlight") for h in get(reference, "hits.hits", [])]
        c.check(got == want, "the product names are highlighted",
                f"first hit: expected {want[0] if want else None}, got {got[0] if got else None}")
        same_aggs(c, answer, reference)
