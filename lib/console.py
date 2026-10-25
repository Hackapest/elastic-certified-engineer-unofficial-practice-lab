"""Parse and run requests written in Kibana Dev Tools console syntax.

    # comment
    GET kibana_sample_data_ecommerce/_search
    {
      "query": { "match_all": {} }
    }

    POST _query
    { "query": \"\"\"FROM flights | LIMIT 5\"\"\" }

    POST _bulk
    {"index": {"_index": "books"}}
    {"title": "Dune"}

Bodies may span lines, use triple-quoted strings, or be NDJSON (bulk, msearch).
"""

import json
import re
from dataclasses import dataclass

REQUEST_LINE = re.compile(r"^\s*(GET|POST|PUT|DELETE|HEAD|PATCH)\s+(\S+)\s*$", re.IGNORECASE)
TRIPLE_QUOTED = re.compile(r'"""(.*?)"""', re.DOTALL)


class ConsoleSyntaxError(Exception):
    pass


@dataclass
class Request:
    method: str
    path: str
    body: object = None        # dict/list for JSON, list of dicts for NDJSON, None for no body
    ndjson: bool = False
    line: int = 0

    def __str__(self):
        return f"{self.method} {self.path}"


def parse(text):
    requests = []
    current, body_lines, in_triple = None, [], False

    def finish():
        if current is not None:
            current.body, current.ndjson = _parse_body(body_lines, current)
            requests.append(current)

    for number, line in enumerate(text.splitlines(), 1):
        match = None if in_triple else REQUEST_LINE.match(line)
        if match:
            finish()
            path = match.group(2)
            current = Request(match.group(1).upper(), path if path.startswith("/") else "/" + path,
                              line=number)
            body_lines = []
        elif not in_triple and line.strip().startswith(("#", "//")):
            continue
        elif current is None:
            if line.strip():
                raise ConsoleSyntaxError(f"line {number}: expected a request line like "
                                         f"`GET index/_search`, found: {line.strip()}")
        else:
            body_lines.append(line)
        if line.count('"""') % 2:
            in_triple = not in_triple
    if in_triple:
        raise ConsoleSyntaxError('unterminated """ string')
    finish()
    if not requests:
        raise ConsoleSyntaxError("no requests found")
    return requests


def _parse_body(lines, request):
    text = "\n".join(lines).strip()
    if not text:
        return None, False
    text = TRIPLE_QUOTED.sub(lambda m: json.dumps(m.group(1)), text)
    try:
        return json.loads(text), False
    except json.JSONDecodeError as whole_error:
        docs = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                docs.append(json.loads(line))
            except json.JSONDecodeError:
                raise ConsoleSyntaxError(
                    f"{request} (line {request.line}): the body is not valid JSON: {whole_error}") from None
        return docs, True


def run(client, requests):
    """Run requests in order. Returns [(request, status, response)]."""
    results = []
    for req in requests:
        if req.body is None:
            data, content_type = None, None
        elif req.ndjson:
            data = "".join(json.dumps(d) + "\n" for d in req.body).encode()
            content_type = "application/x-ndjson"
        else:
            data, content_type = json.dumps(req.body).encode(), "application/json"
        status, response = client.send(req.method, req.path, data, content_type)
        results.append((req, status, response))
    return results
