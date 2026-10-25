from lib.sampledata import ECOMMERCE, FLIGHTS
from lib.tasklib import Task
from tasks.security._helpers import delete_spaces, run_kibana_console, send_json

# (feature ID, name in the Kibana UI)
FEATURES = [("ml", "Machine Learning"), ("maps_v2", "Maps"), ("canvas", "Canvas"), ("graph", "Graph"),
            ("apm", "APM and User Experience"), ("uptime", "Synthetics and Uptime"), ("dev_tools", "Dev Tools"),
            ("siemV5", "Security")]
TEAMS = ["Marketing", "Operations", "Finance", "Support", "Logistics"]


class KibanaSpaces(Task):
    id = "security-kibana-spaces"
    title = "Create a Kibana space with hidden features, and share a data view into it"
    covers = ["security.rbac.spaces"]
    answer = "state"
    requires = ("kibana",)

    def params(self, rnd, iid):
        team = rnd.choice(TEAMS)
        return {"space": f"{team.lower()}-{iid}", "name": f"{team} {iid}", "team": team,
                "disabled": sorted(rnd.sample(FEATURES, 3)), "color": rnd.choice(["#D36086", "#54B399", "#6092C0"]),
                "dv_id": f"flights-{iid}", "dv_name": f"Flights {iid}", "orders_name": f"Orders {iid}"}

    def setup(self, ctx):
        p = ctx.p
        send_json(ctx.kibana(), "POST", "/api/data_views/data_view", {"data_view": {
            "id": p["dv_id"], "title": FLIGHTS, "name": p["dv_name"], "timeFieldName": "timestamp"}})

    def prompt(self, ctx):
        p = ctx.p
        features = ", ".join(name for _, name in p["disabled"])
        return f"""
The {p['team']} team gets its own Kibana space on cluster A (Kibana http://localhost:5601). Use
the Kibana UI or the Kibana APIs.

  1. Create the space with the ID `{p['space']}`, the name "{p['name']}" and the color {p['color']}.
     Hide these features in the space (and only these): {features}.
  2. Copy the data view "{p['dv_name']}" from the Default space into the new space.
  3. In the new space, create a data view named "{p['orders_name']}" for the index {ECOMMERCE},
     with order_date as its time field.
"""

    def solution(self, ctx):
        p = ctx.p
        disabled = ", ".join(f'"{f}"' for f, _ in p["disabled"])
        return f"""
# Kibana API requests: in Dev Tools prefix the path with "kbn:", e.g. POST kbn:/api/spaces/space
POST kbn:/api/spaces/space
{{
  "id": "{p['space']}",
  "name": "{p['name']}",
  "color": "{p['color']}",
  "disabledFeatures": [{disabled}]
}}

POST kbn:/api/spaces/_copy_saved_objects
{{
  "spaces": ["{p['space']}"],
  "objects": [{{ "type": "index-pattern", "id": "{p['dv_id']}" }}]
}}

POST kbn:/s/{p['space']}/api/data_views/data_view
{{
  "data_view": {{
    "title": "{ECOMMERCE}",
    "name": "{p['orders_name']}",
    "timeFieldName": "order_date"
  }}
}}
"""

    def apply_solution(self, ctx):
        """The solution uses the Kibana API, which the console runner (Elasticsearch only) can't send."""
        return run_kibana_console(ctx.kibana(), self.solution(ctx), ctx.es)

    def verify(self, ctx, c):
        p, kibana = ctx.p, ctx.kibana()
        status, space = kibana.send("GET", f"/api/spaces/space/{p['space']}")
        if not c.check(status == 200, f"the space {p['space']} exists"):
            return
        c.equal(space.get("name"), p["name"], "the space has the name")
        c.equal((space.get("color") or "").upper(), p["color"].upper(), "the space has the color")
        c.equal(sorted(space.get("disabledFeatures", [])), sorted(f for f, _ in p["disabled"]),
                "exactly the requested features are hidden")
        status, response = kibana.send("GET", f"/s/{p['space']}/api/data_views")
        views = response.get("data_view", []) if status == 200 else []
        c.check(any(v.get("name") == p["dv_name"] and v.get("title") == FLIGHTS for v in views),
                f'the data view "{p["dv_name"]}" is in the space')
        orders = [v for v in views if v.get("name") == p["orders_name"]]
        if c.check(orders, f'the data view "{p["orders_name"]}" is in the space'):
            c.equal((orders[0].get("title"), orders[0].get("timeFieldName")), (ECOMMERCE, "order_date"),
                    f'"{p["orders_name"]}" is for {ECOMMERCE} with the time field order_date')

    def cleanup(self, ctx):
        kibana = ctx.kibana()
        delete_spaces(kibana, ctx.iid)
        kibana.send("DELETE", f"/api/data_views/data_view/{ctx.p['dv_id']}")
