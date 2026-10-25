import json

from lib.tasklib import Task


class DataStream(Task):
    id = "data-data-stream"
    title = "Set up a data stream, write to it and roll it over"
    covers = ["data.templates.data-stream-template", "data.templates.use-data-stream",
              "data.templates.data-stream-rollover", "data.ilm.manual-rollover", "data.templates.composable"]
    answer = "state"

    def params(self, rnd, iid):
        docs = [{"@timestamp": f"2026-10-{d:02d}T{h:02d}:00:00Z", "device": rnd.choice(["d-1", "d-2", "d-3"]),
                 "temperature": round(rnd.uniform(15, 30), 1)} for d, h in ((1, 8), (1, 12), (2, 9), (3, 17))]
        return {"stream": f"iot-readings-{iid}", "template": f"iot-readings-{iid}", "docs": docs,
                "temp_type": rnd.choice(["float", "half_float"])}

    def prompt(self, ctx):
        p = ctx.p
        docs = "\n".join(f"  {json.dumps(d)}" for d in p["docs"])
        return f"""
Set up the data stream `{p['stream']}` for IoT readings:

  - create an index template named `{p['template']}` so that the data stream gets this mapping:
      @timestamp (date), device (keyword), temperature ({p['temp_type']})
  - create the data stream and add these documents to it:
{docs}
  - then roll the data stream over once, so new documents go to a new backing index
"""

    def solution(self, ctx):
        p = ctx.p
        bulk = "\n".join('{ "create": {} }\n' + json.dumps(d) for d in p["docs"])
        return f"""
PUT _index_template/{p['template']}
{{
  "index_patterns": ["{p['stream']}*"],
  "data_stream": {{}},
  "priority": 500,
  "template": {{
    "mappings": {{
      "properties": {{
        "@timestamp": {{ "type": "date" }},
        "device": {{ "type": "keyword" }},
        "temperature": {{ "type": "{p['temp_type']}" }}
      }}
    }}
  }}
}}

PUT _data_stream/{p['stream']}

POST {p['stream']}/_bulk?refresh=true
{bulk}

POST {p['stream']}/_rollover
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = es.send("GET", f"/_data_stream/{p['stream']}")
        if not c.check(status == 200, f"data stream {p['stream']} exists"):
            return
        ds = response["data_streams"][0]
        c.equal(ds.get("template"), p["template"], f"it uses the template {p['template']}")
        c.check(len(ds.get("indices", [])) >= 2, "it was rolled over (2 or more backing indices)",
                f"it has {len(ds.get('indices', []))} backing index")
        es.send("POST", f"/{p['stream']}/_refresh")
        count = es.send("GET", f"/{p['stream']}/_count")[1] or {}
        c.equal(count.get("count"), len(p["docs"]), "it holds the documents")
        write_index = ds["indices"][-1]["index_name"]
        # (backing index names contain dots, so no get() path here)
        props = es.get(f"/{write_index}/_mapping")[write_index]["mappings"].get("properties", {})
        types = {k: v.get("type") for k, v in props.items() if k in ("@timestamp", "device", "temperature")}
        c.equal(types, {"@timestamp": "date", "device": "keyword", "temperature": p["temp_type"]},
                "the current backing index has the mapping")
