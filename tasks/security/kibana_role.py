from lib.sampledata import ECOMMERCE, FLIGHTS
from lib.tasklib import Task, get
from tasks.security._helpers import count, delete_spaces, err, kibana_as, send_json, as_user

PASSWORD = "kibana-pass-123"


def can_create(kibana_user, kibana_admin, space, so_type, so_id):
    """Try to create a saved object as the user; removes it again. Returns the HTTP status."""
    prefix = f"/s/{space}" if space != "default" else ""
    status, _ = send_json(kibana_user, "POST", f"{prefix}/api/saved_objects/{so_type}/{so_id}",
                          {"attributes": {"title": f"check {so_id}"}})
    if status < 300:
        kibana_admin.send("DELETE", f"{prefix}/api/saved_objects/{so_type}/{so_id}")
    return status


def visible(kibana_user, space, so_type, so_id):
    prefix = f"/s/{space}" if space != "default" else ""
    status, response = kibana_user.send("GET", f"{prefix}/api/saved_objects/_find?type={so_type}&per_page=100")
    return status == 200 and any(o["id"] == so_id for o in response.get("saved_objects", []))


class KibanaRole(Task):
    id = "security-kibana-role"
    title = "A role with Kibana feature privileges in one space and read access in another"
    covers = ["security.rbac.kibana-privileges", "security.rbac.spaces", "security.rbac.roles"]
    answer = "state"
    requires = ("kibana",)

    def params(self, rnd, iid):
        team = rnd.choice(["marketing", "operations", "finance", "support"])
        return {"team": team, "space": f"{team}-{iid}", "shared": f"shared-{iid}", "role": f"{team}-analyst-{iid}",
                "user": f"{team}-user-{iid}", "dashboard": f"kpis-{iid}", "shared_dashboard": f"company-{iid}",
                "index": rnd.choice([FLIGHTS, ECOMMERCE])}

    def setup(self, ctx):
        p, kibana = ctx.p, ctx.kibana()
        for space, dashboard in ((p["space"], p["dashboard"]), (p["shared"], p["shared_dashboard"])):
            send_json(kibana, "POST", "/api/spaces/space", {"id": space, "name": space})
            send_json(kibana, "POST", f"/s/{space}/api/saved_objects/dashboard/{dashboard}",
                      {"attributes": {"title": f"Dashboard {dashboard}"}})

    def prompt(self, ctx):
        p = ctx.p
        return f"""
The Kibana spaces `{p['space']}` and `{p['shared']}` exist on cluster A. Create the role `{p['role']}`
(in Kibana under Stack Management > Roles, or with an API) for analysts of the {p['team']} team:

  - Elasticsearch: read access to the index {p['index']}, nothing else.
  - In the space `{p['space']}`: Discover with all privileges (they can save searches), Dashboard
    read-only (they can open dashboards but not create or change them). No other feature.
  - In the space `{p['shared']}`: read-only access to all features.
  - No access to any other space.

Then create the user `{p['user']}` (password `{PASSWORD}`) with that role.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
# With the Kibana role API (in Dev Tools: PUT kbn:/api/security/role/{p['role']}):
#   {{
#     "elasticsearch": {{ "indices": [{{ "names": ["{p['index']}"], "privileges": ["read"] }}] }},
#     "kibana": [
#       {{ "spaces": ["{p['space']}"], "base": [], "feature": {{ "discover_v2": ["all"], "dashboard_v2": ["read"] }} }},
#       {{ "spaces": ["{p['shared']}"], "base": ["read"] }}
#     ]
#   }}
# The same role with the Elasticsearch API, where Kibana privileges are application privileges:
PUT _security/role/{p['role']}
{{
  "indices": [
    {{ "names": ["{p['index']}"], "privileges": ["read"] }}
  ],
  "applications": [
    {{
      "application": "kibana-.kibana",
      "privileges": ["feature_discover_v2.all", "feature_dashboard_v2.read"],
      "resources": ["space:{p['space']}"]
    }},
    {{
      "application": "kibana-.kibana",
      "privileges": ["space_read"],
      "resources": ["space:{p['shared']}"]
    }}
  ]
}}

PUT _security/user/{p['user']}
{{
  "password": "{PASSWORD}",
  "roles": ["{p['role']}"]
}}
"""

    def verify(self, ctx, c):
        p, admin = ctx.p, ctx.kibana()
        user = kibana_as("a", p["user"], PASSWORD)
        status, spaces = user.send("GET", "/api/spaces/space")
        if not c.check(status == 200, f"{p['user']} can log in to Kibana", err(status, spaces)):
            return
        c.equal(sorted(s["id"] for s in spaces), sorted([p["space"], p["shared"]]),
                f"{p['user']} has access to exactly the spaces {p['space']} and {p['shared']}")
        iid = ctx.iid
        c.check(visible(user, p["space"], "dashboard", p["dashboard"]),
                f"{p['user']} can open dashboards in {p['space']}")
        status = can_create(user, admin, p["space"], "dashboard", f"check-dash-{iid}")
        c.check(status == 403, f"{p['user']} can't create dashboards in {p['space']}", f"HTTP {status}")
        status = can_create(user, admin, p["space"], "search", f"check-search-{iid}")
        c.check(status == 200, f"{p['user']} can save Discover searches in {p['space']}", f"HTTP {status}")
        status = can_create(user, admin, p["space"], "visualization", f"check-vis-{iid}")
        c.check(status == 403, f"{p['user']} has no other feature privileges in {p['space']}",
                f"creating a visualization returned HTTP {status}")
        c.check(visible(user, p["shared"], "dashboard", p["shared_dashboard"]),
                f"{p['user']} can open dashboards in {p['shared']}")
        status = can_create(user, admin, p["shared"], "search", f"check-search-{iid}")
        c.check(status == 403, f"{p['user']} has read-only access in {p['shared']}",
                f"saving a search returned HTTP {status}")
        status = can_create(user, admin, "default", "search", f"check-search-{iid}")
        c.check(status == 403, f"{p['user']} can't save anything in the Default space", f"HTTP {status}")
        es_user = as_user("a", p["user"], PASSWORD)
        status, n = count(es_user, p["index"])
        c.check(status == 200 and n, f"{p['user']} can read {p['index']}", f"search returned HTTP {status}")
        other = ECOMMERCE if p["index"] == FLIGHTS else FLIGHTS
        status, _ = count(es_user, other)
        c.check(status == 403, f"{p['user']} can't read {other}", f"search returned HTTP {status}")
        status, _ = send_json(es_user, "POST", f"/{p['index']}/_doc", {"x": 1})
        c.check(status == 403, f"{p['user']} can't write to {p['index']}", f"the write returned HTTP {status}")

    def cleanup(self, ctx):
        delete_spaces(ctx.kibana(), ctx.iid)
