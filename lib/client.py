"""Minimal JSON-over-HTTP clients for Elasticsearch and Kibana (standard library only)."""

import base64
import json
import ssl
import urllib.error
import urllib.request

from . import config


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class Client:
    def __init__(self, base_url, user, password, headers=None, ca_cert=None):
        self.base_url = base_url
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", **(headers or {})}
        self.ssl_context = ssl.create_default_context(cafile=str(ca_cert)) if ca_cert else None

    def request(self, method, path, body=None, timeout=30):
        data = None
        headers = dict(self.headers)
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_context) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                raise HttpError(e.code, json.loads(raw)) from None
            except json.JSONDecodeError:
                raise HttpError(e.code, raw.decode(errors="replace")) from None
        return json.loads(raw) if raw else None

    def send(self, method, path, data=None, content_type=None, timeout=120):
        """Low-level request that never raises for HTTP errors: returns (status, parsed body)."""
        headers = dict(self.headers)
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_context) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        try:
            return status, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return status, raw.decode(errors="replace")

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body, **kw)

    def put(self, path, body=None, **kw):
        return self.request("PUT", path, body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def reachable(self, path="/"):
        try:
            self.get(path, timeout=5)
            return True
        except (OSError, HttpError):
            return False


def es(cluster, user="elastic", password=None):
    return Client(config.es_url(cluster), user, password or config.ELASTIC_PASSWORD,
                  ca_cert=config.CA_CERT)


def kibana(cluster):
    # Sample data and some other endpoints are internal APIs in Kibana 9.x
    headers = {"kbn-xsrf": "true", "x-elastic-internal-origin": "Kibana"}
    return Client(config.kibana_url(cluster), "elastic", config.ELASTIC_PASSWORD, headers=headers)
