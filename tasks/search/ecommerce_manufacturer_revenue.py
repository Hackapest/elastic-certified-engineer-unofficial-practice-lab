from lib.tasklib import Task

INDEX = "kibana_sample_data_ecommerce"
CONTINENTS = ["Asia", "North America", "Europe", "Africa"]


class ManufacturerRevenue(Task):
    id = "search-ecommerce-manufacturer-revenue"
    title = "Top manufacturers by revenue, with a sub-aggregation"
    covers = [
        "search.bucket-aggs.terms", "search.metric-aggs.sum", "search.metric-aggs.avg",
        "search.aggs.sub-aggregations", "search.aggs.aggs-with-query",
    ]
    answer = "query"
    compare = "aggs"

    def params(self, rnd, iid):
        return {"continent": rnd.choice(CONTINENTS), "top": rnd.choice([3, 4, 5])}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
In `{INDEX}`, look only at orders from customers in {p['continent']} (geoip.continent_name).

Find the {p['top']} manufacturers (manufacturer.keyword) with the highest total revenue, where
revenue is the sum of taxful_total_price. For each of them return:

  - the total revenue
  - the average number of items per order (total_quantity)

Sort them by total revenue, highest first. Return no documents, only the aggregation results,
and use no other aggregations than the ones needed for this.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {INDEX}/_search
{{
  "size": 0,
  "query": {{
    "term": {{ "geoip.continent_name": "{p['continent']}" }}
  }},
  "aggs": {{
    "manufacturers": {{
      "terms": {{
        "field": "manufacturer.keyword",
        "size": {p['top']},
        "order": {{ "revenue": "desc" }}
      }},
      "aggs": {{
        "revenue": {{ "sum": {{ "field": "taxful_total_price" }} }},
        "avg_items": {{ "avg": {{ "field": "total_quantity" }} }}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Lowest revenue first
        return self.solution(ctx).replace('"order": { "revenue": "desc" }', '"order": { "revenue": "asc" }')
