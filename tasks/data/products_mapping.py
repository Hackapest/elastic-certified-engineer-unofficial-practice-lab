from lib.tasklib import Task, field_mapping, index_settings

DATE_FORMATS = ["dd/MM/yyyy", "yyyy-MM-dd HH:mm", "MM-dd-yyyy", "yyyy/MM/dd"]
FIELDS = {"name", "sku", "price", "tags", "in_stock", "added", "description"}


class ProductsMapping(Task):
    id = "data-products-mapping"
    title = "Products index with an explicit mapping"
    covers = [
        "ingest.mapping.explicit", "data.index.shards-replicas", "ingest.types.text", "ingest.types.keyword",
        "ingest.types.numeric", "ingest.types.boolean", "ingest.types.date", "ingest.types.arrays",
        "ingest.mapping.param.fields", "ingest.mapping.param.ignore-above", "ingest.mapping.param.format",
        "ingest.mapping.param.analyzer", "data.analysis.analyzer.language", "data.dynamic.dynamic-parameter",
    ]
    answer = "state"

    def params(self, rnd, iid):
        return {
            "index": f"products-{iid}",
            "shards": rnd.choice([1, 2, 3]),
            "replicas": rnd.choice([0, 1, 2]),
            "ignore_above": rnd.choice([64, 128, 256]),
            "scaling_factor": rnd.choice([100, 1000]),
            "date_format": rnd.choice(DATE_FORMATS),
            "language": rnd.choice(["english", "german", "french"]),
        }

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Create an index named `{p['index']}` with {p['shards']} primary shard(s) and {p['replicas']} replica(s).
Its mapping must have exactly these fields:

  name         full-text searchable, plus a sub-field `name.raw` for exact matching,
               sorting and aggregations that ignores values longer than {p['ignore_above']} characters
  sku          exact values only
  price        a price with decimals, stored as a scaled float with scaling factor {p['scaling_factor']}
  tags         exact values; a document can have several tags
  in_stock     true or false
  added        a date in the format {p['date_format']}
  description  full-text searchable, analyzed with the built-in {p['language']} analyzer

Indexing a document that contains any other field must be rejected.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT {p['index']}
{{
  "settings": {{
    "number_of_shards": {p['shards']},
    "number_of_replicas": {p['replicas']}
  }},
  "mappings": {{
    "dynamic": "strict",
    "properties": {{
      "name": {{
        "type": "text",
        "fields": {{
          "raw": {{ "type": "keyword", "ignore_above": {p['ignore_above']} }}
        }}
      }},
      "sku": {{ "type": "keyword" }},
      "price": {{ "type": "scaled_float", "scaling_factor": {p['scaling_factor']} }},
      "tags": {{ "type": "keyword" }},
      "in_stock": {{ "type": "boolean" }},
      "added": {{ "type": "date", "format": "{p['date_format']}" }},
      "description": {{ "type": "text", "analyzer": "{p['language']}" }}
    }}
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        settings = index_settings(es, p["index"])
        if not c.check(settings is not None, f"index {p['index']} exists"):
            return
        c.equal(settings.get("index.number_of_shards"), str(p["shards"]), "number of primary shards")
        c.equal(settings.get("index.number_of_replicas"), str(p["replicas"]), "number of replicas")

        mapping = es.get(f"/{p['index']}/_mapping")[p["index"]]["mappings"]
        c.equal(set(mapping.get("properties", {})), FIELDS, "the mapping has exactly the requested fields")
        c.equal(mapping.get("dynamic"), "strict", "documents with unknown fields are rejected (dynamic)")

        def field(name):
            return field_mapping(es, p["index"], name) or {}

        c.equal(field("name").get("type"), "text", "name is a text field")
        raw = field("name.raw")
        c.equal((raw.get("type"), raw.get("ignore_above")), ("keyword", p["ignore_above"]),
                "name.raw is a keyword sub-field with the requested ignore_above")
        c.equal(field("sku").get("type"), "keyword", "sku is a keyword field")
        price = field("price")
        c.equal((price.get("type"), price.get("scaling_factor")), ("scaled_float", float(p["scaling_factor"])),
                "price is a scaled_float with the requested scaling factor")
        c.equal(field("tags").get("type"), "keyword", "tags is a keyword field (arrays need no special type)")
        c.equal(field("in_stock").get("type"), "boolean", "in_stock is a boolean field")
        added = field("added")
        c.equal((added.get("type"), added.get("format")), ("date", p["date_format"]),
                "added is a date field with the requested format")
        description = field("description")
        c.equal((description.get("type"), description.get("analyzer")), ("text", p["language"]),
                f"description is a text field with the {p['language']} analyzer")
