import json

from lib.tasklib import Task, same_aggs, same_hits


class CatalogIndexMetadata(Task):
    id = "search-catalog-index-metadata"
    title = "Search several indices at once and use _index and _id"
    covers = ["ingest.mapping.meta.index", "ingest.mapping.meta.id", "search.fulltext.match-all",
              "search.term.ids", "search.basics.multi-index", "search.bucket-aggs.terms"]
    answer = "query"

    def params(self, rnd, iid):
        return {"prefix": f"catalog-{iid}", "regions": ["eu", "us", "apac"], "region": rnd.choice(["eu", "us", "apac"]),
                "ids": sorted(rnd.sample(range(1, 30), 4)),
                "sizes": {r: rnd.randint(20, 40) for r in ("eu", "us", "apac")}}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        for region in p["regions"]:
            bulk = "".join(json.dumps({"index": {"_id": f"p{i}"}}) + "\n" +
                           json.dumps({"product": f"product {i}", "region": region}) + "\n"
                           for i in range(1, p["sizes"][region] + 1))
            es.send("POST", f"/{p['prefix']}-{region}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        ids = ", ".join(f"p{i}" for i in p["ids"])
        names = ", ".join(f"`{p['prefix']}-{r}`" for r in p["regions"])
        return f"""
The product catalog is split into the indices {names}; all use the same
document IDs (p1, p2, ...). With ONE search request over all three indices (use a wildcard):

  - return the documents with the IDs {ids} that are in `{p['prefix']}-{p['region']}`, and only those
  - also return the total number of documents in each of the three indices, as buckets of a
    terms aggregation on the index name
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {p['prefix']}-*/_search
{{
  "post_filter": {{
    "bool": {{
      "filter": [
        {{ "term": {{ "_index": "{p['prefix']}-{p['region']}" }} }},
        {{ "ids": {{ "values": {json.dumps([f"p{i}" for i in p['ids']])} }} }}
      ]
    }}
  }},
  "query": {{ "match_all": {{}} }},
  "aggs": {{
    "per_index": {{ "terms": {{ "field": "_index" }} }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        # Filters in the query, so the aggregation only counts the selected documents
        return self.solution(ctx).replace('"post_filter"', '"query"').replace(
            ',\n  "query": { "match_all": {} }', "")

    def grade(self, ctx, c, answer, reference):
        same_hits(c, answer, reference, ordered=False)
        same_aggs(c, answer, reference)
