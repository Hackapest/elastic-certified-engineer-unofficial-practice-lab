import fnmatch
import re

from lib.tasklib import Task, get


def _value_matches(pattern, value):
    if pattern is None:
        return value is None
    if value is None:
        return False
    if isinstance(pattern, (int, float, bool)):
        return pattern == value
    if pattern.startswith("/") and pattern.endswith("/") and len(pattern) > 1:
        return re.fullmatch(pattern[1:-1], str(value)) is not None
    return fnmatch.fnmatchcase(str(value).lower(), pattern.lower())


def rule_matches(rule, subject):
    """Evaluate a role mapping rule (all/any/except/field) for a user's attributes, like Elasticsearch."""
    if "all" in rule:
        return all(rule_matches(r, subject) for r in rule["all"])
    if "any" in rule:
        return any(rule_matches(r, subject) for r in rule["any"])
    if "except" in rule:
        return not rule_matches(rule["except"], subject)
    if "field" in rule:
        for name, patterns in rule["field"].items():
            values = subject.get(name)
            values = values if isinstance(values, list) else [values]
            patterns = patterns if isinstance(patterns, list) else [patterns]
            if not any(_value_matches(pt, v) for pt in patterns for v in values):
                return False
        return True
    return False


class RoleMapping(Task):
    id = "security-role-mapping"
    title = "Role mappings for users of an external realm, by group and by username"
    covers = ["security.rbac.role-mapping"]
    answer = "state"

    def params(self, rnd, iid):
        dept = rnd.choice(["engineering", "finance", "research"])
        return {"admins_map": f"{dept}-admins-{iid}", "ext_map": f"contractors-{iid}", "realm": f"ldap-{dept}",
                "admin_group": f"cn={dept}-admins,ou=groups,dc=example,dc=com",
                "blocked_group": "cn=suspended,ou=groups,dc=example,dc=com",
                "admin_roles": ["monitoring_user", rnd.choice(["snapshot_user", "ingest_admin"])],
                "ext_role": "viewer", "suffix": rnd.choice(["_ext", "_contractor", "_vendor"])}

    def subjects(self, p):
        """(description, user attributes, expected roles)"""
        g, b, s, realm = p["admin_group"], p["blocked_group"], p["suffix"], p["realm"]
        admins, ext = sorted(p["admin_roles"]), [p["ext_role"]]
        return [
            ("an admin group member of the realm", {"username": "jdoe", "realm.name": realm, "groups": [g]}, admins),
            ("an admin group member of another realm", {"username": "jdoe", "realm.name": "saml1", "groups": [g]}, []),
            ("a realm user outside the admin group", {"username": "asmith", "realm.name": realm,
                                                      "groups": ["cn=staff,ou=groups,dc=example,dc=com"]}, []),
            (f"a user named *{s}", {"username": f"bob{s}", "realm.name": realm, "groups": []}, ext),
            (f"a user named *{s} in another realm", {"username": f"eve{s}", "realm.name": "saml1", "groups": []}, ext),
            (f"a suspended user named *{s}", {"username": f"tom{s}", "realm.name": realm, "groups": [b]}, []),
            (f"an admin named *{s}", {"username": f"ann{s}", "realm.name": realm, "groups": [g]},
             sorted(set(admins + ext))),
        ]

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Cluster A will authenticate employees through an LDAP realm named `{p['realm']}` (not configured
yet; role mappings can be created before the realm exists). Create two role mappings:

  1. `{p['admins_map']}`: users of the realm `{p['realm']}` who are members of the group
     "{p['admin_group']}" get the built-in roles {' and '.join(p['admin_roles'])}.
  2. `{p['ext_map']}`: users of any realm whose username ends with "{p['suffix']}" get the role
     {p['ext_role']}, unless they are members of the group "{p['blocked_group']}".

Both mappings must be enabled.
"""

    def solution(self, ctx):
        p = ctx.p
        roles = ", ".join(f'"{r}"' for r in p["admin_roles"])
        return f"""
PUT _security/role_mapping/{p['admins_map']}
{{
  "enabled": true,
  "roles": [{roles}],
  "rules": {{
    "all": [
      {{ "field": {{ "realm.name": "{p['realm']}" }} }},
      {{ "field": {{ "groups": "{p['admin_group']}" }} }}
    ]
  }}
}}

PUT _security/role_mapping/{p['ext_map']}
{{
  "enabled": true,
  "roles": ["{p['ext_role']}"],
  "rules": {{
    "all": [
      {{ "field": {{ "username": "*{p['suffix']}" }} }},
      {{ "except": {{ "field": {{ "groups": "{p['blocked_group']}" }} }} }}
    ]
  }}
}}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        mappings = {}
        for name in (p["admins_map"], p["ext_map"]):
            status, response = es.send("GET", f"/_security/role_mapping/{name}")
            if c.check(status == 200, f"role mapping {name} exists"):
                mappings[name] = response[name]
                c.check(response[name].get("enabled") is True, f"{name} is enabled")
        if len(mappings) < 2:
            return
        for description, subject, expected in self.subjects(p):
            roles = set()
            for m in mappings.values():
                if m.get("roles") is None or m.get("role_templates"):
                    continue
                if rule_matches(m.get("rules", {}), subject):
                    roles.update(m["roles"])
            c.equal(sorted(roles), expected, f"{description} gets {', '.join(expected) or 'no roles'}")

    def cleanup(self, ctx):
        status, response = ctx.es.send("GET", "/_security/role_mapping")
        for name in (response or {}) if status == 200 else {}:
            if ctx.iid in name:
                ctx.es.send("DELETE", f"/_security/role_mapping/{name}")
