import json

from lib.tasklib import Task, get

SENSORS = ["boiler-1", "boiler-2", "pump-1", "test-rig-1", "test-rig-2"]


class DataStreamUpdateDelete(Task):
    id = "data-data-stream-update-delete"
    title = "Fix, delete and backfill documents in a data stream"
    covers = ["data.templates.data-stream-update-delete", "ingest.reindex.reindex-data-stream",
              "ingest.reindex.update-by-query", "ingest.reindex.delete-by-query",
              "ingest.reindex.reindex-options"]
    answer = "state"

    def params(self, rnd, iid):
        docs = []
        for i in range(rnd.randint(40, 70)):
            sensor = SENSORS[i % len(SENSORS)]
            unit = "F" if rnd.random() < 0.3 else "C"
            celsius = round(rnd.uniform(20, 90), 1)
            docs.append({"@timestamp": f"2026-10-{1 + i % 20:02d}T{i % 24:02d}:00:00Z", "sensor": sensor,
                         "unit": unit, "temperature": round(celsius * 9 / 5 + 32, 1) if unit == "F" else celsius})
        archive = [{"ts": f"2026-09-{1 + i % 28:02d}T12:00:00Z", "sensor": rnd.choice(SENSORS[:3]),
                    "unit": "C", "temperature": round(rnd.uniform(20, 90), 1)} for i in range(rnd.randint(10, 25))]
        return {"stream": f"sensors-{iid}", "archive": f"sensor-archive-{iid}", "docs": docs, "archive_docs": archive}

    def setup(self, ctx):
        p, es = ctx.p, ctx.es
        es.put(f"/_index_template/{p['stream']}", {
            "index_patterns": [f"{p['stream']}*"], "data_stream": {}, "priority": 500,
            "template": {"mappings": {"properties": {"sensor": {"type": "keyword"}, "unit": {"type": "keyword"},
                                                     "temperature": {"type": "float"}}}}})
        bulk = "".join('{"create":{}}\n' + json.dumps(d) + "\n" for d in p["docs"])
        es.send("POST", f"/{p['stream']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")
        es.put(f"/{p['archive']}", {"mappings": {"properties": {"ts": {"type": "date"}, "sensor": {"type": "keyword"},
                                                               "unit": {"type": "keyword"},
                                                               "temperature": {"type": "float"}}}})
        bulk = "".join('{"index":{}}\n' + json.dumps(d) + "\n" for d in p["archive_docs"])
        es.send("POST", f"/{p['archive']}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The data stream `{p['stream']}` holds temperature readings (fields sensor, unit, temperature).

  1. Some devices reported Fahrenheit (unit "F"). Convert those documents in place to Celsius:
     temperature = (temperature - 32) * 5 / 9, unit = "C".
  2. Delete all readings from the test rigs (sensor names starting with "test-rig").
  3. Readings from September are in the regular index `{p['archive']}`, with the time in the field
     `ts` instead of @timestamp. Copy them all into the data stream, with the time in @timestamp
     and without a `ts` field.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
POST {p['stream']}/_update_by_query?refresh=true
{{
  "query": {{ "term": {{ "unit": "F" }} }},
  "script": {{
    "source": "ctx._source.temperature = (ctx._source.temperature - 32) * 5 / 9; ctx._source.unit = 'C';"
  }}
}}

POST {p['stream']}/_delete_by_query?refresh=true
{{
  "query": {{ "prefix": {{ "sensor": "test-rig" }} }}
}}

POST _reindex?refresh=true
{{
  "source": {{ "index": "{p['archive']}" }},
  "dest": {{ "index": "{p['stream']}", "op_type": "create" }},
  "script": {{
    "source": "ctx._source['@timestamp'] = ctx._source.remove('ts');"
  }}
}}
"""

    def expected(self, p):
        kept = [d for d in p["docs"] if not d["sensor"].startswith("test-rig")]
        celsius = [(d["temperature"] - 32) * 5 / 9 if d["unit"] == "F" else d["temperature"] for d in kept]
        return len(kept) + len(p["archive_docs"]), sum(celsius) + sum(d["temperature"] for d in p["archive_docs"])

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        search = lambda body: es.send("POST", f"/{p['stream']}/_search", json.dumps(body).encode(),
                                      "application/json")[1] or {}
        es.send("POST", f"/{p['stream']}/_refresh")
        count, total = self.expected(p)
        r = search({"size": 0, "track_total_hits": True,
                    "aggs": {"units": {"terms": {"field": "unit"}}, "rigs": {"filter": {"prefix": {"sensor": "test-rig"}}},
                             "ts": {"filter": {"exists": {"field": "ts"}}},
                             "no_ts": {"filter": {"bool": {"must_not": {"exists": {"field": "@timestamp"}}}}},
                             "sum": {"sum": {"field": "temperature"}}}})
        units = {b["key"]: b["doc_count"] for b in get(r, "aggregations.units.buckets", [])}
        c.equal(units.get("F", 0), 0, "no readings are left in Fahrenheit")
        c.equal(get(r, "aggregations.rigs.doc_count"), 0, "the test rig readings are deleted")
        c.equal(get(r, "hits.total.value"), count, "the data stream has the expected number of documents")
        c.check(get(r, "aggregations.ts.doc_count") == 0 and get(r, "aggregations.no_ts.doc_count") == 0,
                "every document has @timestamp and none has ts")
        got = get(r, "aggregations.sum.value") or 0
        c.check(abs(got - total) < 0.5 + 0.001 * abs(total), "the temperatures are converted correctly",
                f"sum of temperatures: expected {total:.1f}, found {got:.1f}")
        archive = (es.send("GET", f"/{p['archive']}/_count")[1] or {}).get("count")
        c.equal(archive, len(p["archive_docs"]), f"{p['archive']} keeps its documents")
