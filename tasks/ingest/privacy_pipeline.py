import random

from lib import client
from lib.tasklib import Task
from tasks.ingest._common import check_against_reference, render_pipeline, send

FIRST = ["jane", "omar", "li", "sara", "tom", "ines", "kofi"]
LAST = ["doe", "khan", "wei", "berg", "novak", "silva"]
DOMAINS = ["example.com", "mail.example.org", "corp.example.net"]
TEMPLATES = ["login from {ip} by {email} failed", "password reset requested by {email}",
             "{email} downloaded invoice 4411 from {ip}", "session started from {ip}",
             "newsletter bounce for {email}, retried from {ip}"]


def customer(rnd):
    first, last = rnd.choice(FIRST), rnd.choice(LAST)
    email = f"{first}.{last}@{rnd.choice(DOMAINS)}"
    ip = f"{rnd.randint(1, 223)}.{rnd.randint(0, 255)}.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}"
    return {"message": rnd.choice(TEMPLATES).format(ip=ip, email=email),
            "customer": {"email": email, "name": f"{first.title()} {last.title()}"}}


class PrivacyPipeline(Task):
    id = "ingest-privacy-pipeline"
    title = "Mask personal data and record who ingested it (redact, fingerprint, set_security_user)"
    covers = ["ingest.pipelines.processor.redact", "ingest.pipelines.processor.fingerprint",
              "ingest.pipelines.processor.set_security_user", "ingest.pipelines.processor.remove"]

    def params(self, rnd, iid):
        return {"pipeline": f"pii-mask-{iid}", "salt": rnd.choice(["s3cr3t", "pepper42", "nacl-7"]),
                "method": rnd.choice(["SHA-256", "SHA-512", "MD5"]),
                "email_tag": rnd.choice(["EMAIL", "MAIL"]), "ip_tag": rnd.choice(["IP", "CLIENT_IP"]),
                "examples": [customer(rnd) for _ in range(2)]}

    def processors(self, p):
        return [
            {"redact": {"field": "message", "patterns": [f"%{{EMAILADDRESS:{p['email_tag']}}}",
                                                         f"%{{IP:{p['ip_tag']}}}"]}},
            {"fingerprint": {"fields": ["customer.email", "customer.name"], "target_field": "customer.id",
                             "method": p["method"], "salt": p["salt"]}},
            {"remove": {"field": "customer.email"}},
            {"set_security_user": {"field": "ingested_by", "properties": ["username"]}},
        ]

    def prompt(self, ctx):
        p = ctx.p
        e = p["examples"][0]
        return f"""
Customer events contain personal data, for example:

  {{ "message": "{e['message']}",
    "customer": {{ "email": "{e['customer']['email']}", "name": "{e['customer']['name']}" }} }}

Create an ingest pipeline `{p['pipeline']}` that:

  1. replaces every email address in `message` with <{p['email_tag']}> and every IP address with
     <{p['ip_tag']}> (e.g. "login from <{p['ip_tag']}> by <{p['email_tag']}> failed")
  2. stores in `customer.id` a fingerprint of customer.email and customer.name, computed by the
     fingerprint processor with the {p['method']} method and the salt "{p['salt']}"
  3. removes customer.email (customer.name stays)
  4. stores the user name of the user who sends the document in `ingested_by.username`
     (and nothing else under ingested_by)
"""

    def solution(self, ctx):
        return render_pipeline(ctx.p["pipeline"], self.processors(ctx.p))

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        # Simulate as a throwaway user, so ingested_by can't be hard-coded
        user, password = f"pii-checker-{ctx.iid}", f"pw-{random.randrange(10**9)}-checker"
        send(es, "PUT", f"/_security/role/{user}", {"cluster": ["manage_pipeline"]})
        send(es, "PUT", f"/_security/user/{user}", {"password": password, "roles": [user]})
        try:
            rnd = random.Random()
            docs = [customer(rnd) for _ in range(6)]
            checks = [("message is redacted as requested", "message"),
                      ("customer.id is the requested fingerprint", "customer.id"),
                      ("customer.email is removed and customer.name kept",
                       lambda r: (r["source"].get("customer", {}).get("email"),
                                  r["source"].get("customer", {}).get("name"))),
                      ("ingested_by holds the user name of the sender", "ingested_by")]
            check_against_reference(c, client.es(ctx.task.cluster, user, password), p["pipeline"],
                                    self.processors(p), docs, checks)
        finally:
            send(es, "DELETE", f"/_security/user/{user}")
            send(es, "DELETE", f"/_security/role/{user}")
