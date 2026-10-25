from datetime import datetime

from lib.tasklib import Task
from tasks.security._helpers import NODES, node_sh, q

HOME = "/usr/share/elasticsearch"
KEYTOOL = f"{HOME}/jdk/bin/keytool"
ORGS = ["Acme", "Globex", "Initech", "Umbrella", "Hooli"]


def parse_keytool(text):
    """Certificates in keytool -v output: [{alias, entry, owner, issuer, valid_from, valid_until, dns, ip, ca}]."""
    certs, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Alias name:") or (line.startswith("Owner:") and (cur is None or cur.get("owner"))):
            cur = {"alias": None, "entry": None, "owner": None, "issuer": None, "dns": set(), "ip": set(),
                   "ca": False, "valid_from": None, "valid_until": None}
            certs.append(cur)
        if cur is None:
            continue
        if line.startswith("Alias name:"):
            cur["alias"] = line.split(":", 1)[1].strip()
        elif line.startswith("Entry type:"):
            cur["entry"] = line.split(":", 1)[1].strip()
        elif line.startswith("Owner:"):
            cur["owner"] = line.split(":", 1)[1].strip()
        elif line.startswith("Issuer:") and cur["issuer"] is None:
            cur["issuer"] = line.split(":", 1)[1].strip()
        elif line.startswith("Valid from:") and cur["valid_from"] is None:
            start, _, end = line[len("Valid from:"):].partition("until:")
            cur["valid_from"], cur["valid_until"] = _date(start), _date(end)
        elif line.startswith("DNSName:"):
            cur["dns"].add(line.split(":", 1)[1].strip())
        elif line.startswith("IPAddress:"):
            cur["ip"].add(line.split(":", 1)[1].strip())
        elif line == "CA:true":
            cur["ca"] = True
    return certs


def _date(text):
    try:
        return datetime.strptime(text.strip(), "%a %b %d %H:%M:%S %Z %Y")
    except ValueError:
        return None


def keystore_certs(node, path, password):
    code, out = node_sh(node, f"{KEYTOOL} -list -v -storetype PKCS12 -keystore {q(path)} -storepass {q(password)}")
    return (parse_keytool(out), None) if code == 0 else ([], out.strip().splitlines()[-1] if out.strip() else "error")


def pem_cert(node, path):
    code, out = node_sh(node, f"{KEYTOOL} -printcert -v -file {q(path)}")
    return (parse_keytool(out), None) if code == 0 else ([], out.strip().splitlines()[-1] if out.strip() else "error")


class Certutil(Task):
    id = "security-certutil"
    title = "Generate a CA and a node certificate with elasticsearch-certutil"
    covers = ["security.production.certutil", "security.production.setup-tls"]
    answer = "state"
    requires = ("shell",)

    def params(self, rnd, iid):
        org = rnd.choice(ORGS)
        name = rnd.choice(["search-node", "ingest-gw", "es-coord", "kibana-web"])
        domain = f"{org.lower()}.internal"
        return {"node": rnd.choice(NODES["a"]), "dir": f"{HOME}/config/pki-{iid}", "org": org,
                "ca_dn": f"CN={org} Lab CA {iid}", "ca_pass": f"ca-{rnd.randint(1000, 9999)}",
                "ca_days": rnd.choice([730, 1095, 1825]), "name": name,
                "dns": sorted([f"{name}.{domain}", name]), "ip": f"10.{rnd.randint(1, 250)}.{rnd.randint(1, 250)}.10",
                "cert_days": rnd.choice([365, 397, 500]), "pem": rnd.random() < 0.5,
                "cert_pass": f"node-{rnd.randint(1000, 9999)}"}

    def files(self, p):
        d = p["dir"]
        if p["pem"]:
            return {"ca": f"{d}/ca.p12", "crt": f"{d}/{p['name']}/{p['name']}.crt",
                    "key": f"{d}/{p['name']}/{p['name']}.key"}
        return {"ca": f"{d}/ca.p12", "cert": f"{d}/{p['name']}.p12"}

    def prompt(self, ctx):
        p, f = ctx.p, self.files(ctx.p)
        short = p["node"].replace("es-", "")
        if p["pem"]:
            out = f"""in PEM format, unencrypted: the certificate in `{f['crt']}` and the private key
     in `{f['key']}` (certutil writes PEM files into a zip archive: extract it there)"""
        else:
            out = f"as a PKCS#12 keystore `{f['cert']}` with the password `{p['cert_pass']}`"
        return f"""
In the container of the node {p['node']} (`./ece shell {short}`), prepare certificates for a new
service with elasticsearch-certutil. Put all files in the directory `{p['dir']}`.

  1. A new certificate authority: the distinguished name "{p['ca_dn']}", valid for {p['ca_days']}
     days, saved as the PKCS#12 file `{f['ca']}` with the password `{p['ca_pass']}`.
  2. A certificate signed by that CA, with the name (CN) `{p['name']}`, valid for {p['cert_days']} days,
     for the host names {' and '.join(p['dns'])} and the IP address {p['ip']} (subject alternative
     names), saved {out}.

You can inspect the files with keytool: {KEYTOOL} -list -v -keystore <file>
(for a PEM certificate: keytool -printcert -file <file>).
"""

    def commands(self, p):
        f = self.files(p)
        ca = (f"bin/elasticsearch-certutil ca --out {f['ca']} --pass {p['ca_pass']} "
              f"--ca-dn \"{p['ca_dn']}\" --days {p['ca_days']}")
        cert = (f"bin/elasticsearch-certutil cert --ca {f['ca']} --ca-pass {p['ca_pass']} --name {p['name']} "
                f"--dns {','.join(p['dns'])} --ip {p['ip']} --days {p['cert_days']}")
        if p["pem"]:
            return [f"mkdir -p {p['dir']}", ca, f"{cert} --pem --out {p['dir']}/{p['name']}.zip",
                    f"cd {p['dir']} && unzip {p['name']}.zip"]
        return [f"mkdir -p {p['dir']}", ca, f"{cert} --out {f['cert']} --pass {p['cert_pass']}"]

    def solution(self, ctx):
        p = ctx.p
        lines = "\n".join(self.commands(p))
        return f"""
# In a shell in the node: ./ece shell {p['node'].replace('es-', '')}
# (the working directory is {HOME}; add --silent to skip the prompts)
{lines}

# Inspect the result:
{KEYTOOL} -list -v -keystore {self.files(p).get('cert', self.files(p)['ca'])}
"""

    def apply_solution(self, ctx):
        script = " && ".join(c.replace("certutil ca ", "certutil ca --silent ").replace(
            "certutil cert ", "certutil cert --silent ") for c in self.commands(ctx.p))
        code, out = node_sh(ctx.p["node"], script)
        return None if code == 0 else out[-500:]

    def verify(self, ctx, c):
        p, f, node = ctx.p, self.files(ctx.p), ctx.p["node"]
        certs, error = keystore_certs(node, f["ca"], p["ca_pass"])
        if not c.check(certs, f"{f['ca']} is a PKCS#12 file that opens with the password `{p['ca_pass']}`", error):
            return
        ca = next((x for x in certs if x["entry"] == "PrivateKeyEntry"), None)
        if not c.check(ca, "the CA file holds the CA certificate and its private key",
                       "no private key entry in the file"):
            return
        c.check(ca["ca"] and ca["owner"] == ca["issuer"], "it is a self-signed CA certificate")
        c.equal(ca["owner"], p["ca_dn"], "the CA has the distinguished name")
        days = (ca["valid_until"] - ca["valid_from"]).days if ca["valid_from"] and ca["valid_until"] else None
        c.equal(days, p["ca_days"], "the CA has the validity")
        if p["pem"]:
            certs, error = pem_cert(node, f["crt"])
            if not c.check(certs, f"{f['crt']} is a PEM certificate", error):
                return
            cert = certs[0]
            code, out = node_sh(node, f"head -1 {q(f['key'])}")
            c.check(code == 0 and "PRIVATE KEY" in out and "ENCRYPTED" not in out,
                    f"{f['key']} is an unencrypted PEM private key", out.strip()[:200])
        else:
            certs, error = keystore_certs(node, f["cert"], p["cert_pass"])
            if not c.check(certs, f"{f['cert']} is a PKCS#12 file that opens with the password `{p['cert_pass']}`",
                           error):
                return
            cert = next((x for x in certs if x["entry"] == "PrivateKeyEntry"), None)
            if not c.check(cert, "the keystore holds the certificate and its private key"):
                return
        c.equal(cert["owner"], f"CN={p['name']}", "the certificate has the name")
        c.equal(cert["issuer"], p["ca_dn"], "the certificate is signed by the new CA")
        c.check(not cert["ca"], "the certificate is not a CA")
        c.equal(sorted(cert["dns"]), p["dns"], "the certificate has the host names")
        c.equal(sorted(cert["ip"]), [p["ip"]], "the certificate has the IP address")
        days = (cert["valid_until"] - cert["valid_from"]).days if cert["valid_from"] and cert["valid_until"] else None
        c.equal(days, p["cert_days"], "the certificate has the validity")

    def cleanup(self, ctx):
        for node in NODES["a"] + NODES["b"]:
            node_sh(node, f"rm -rf {q(ctx.p['dir'])}")
