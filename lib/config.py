"""Paths and settings shared by the CLI, read from the repository's .env file."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Overridable so the lab can be tested without touching real progress
STATE_DIR = Path(os.environ.get("ECE_STATE_DIR", ROOT / ".state"))
CA_CERT = STATE_DIR / "ca.crt"

CLUSTERS = ("a", "b")
NODES = tuple(f"es-{c}{i}" for c in CLUSTERS for i in (1, 2, 3))

# Rough memory footprint per container, used by the preflight check
KIBANA_MEMORY_GB = 1.2
ES_OFFHEAP_GB = 1.0


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            # Like docker compose, variables set in the shell win over .env
            env[key.strip()] = os.environ.get(key.strip(), value.strip())
    return env


ENV = load_env()
ELASTIC_PASSWORD = ENV["ELASTIC_PASSWORD"]
KIBANA_SYSTEM_PASSWORD = ENV["KIBANA_SYSTEM_PASSWORD"]


def es_url(cluster):
    return f"https://localhost:{ENV[f'ES_{cluster.upper()}_PORT']}"


def kibana_url(cluster):
    return f"http://localhost:{ENV[f'KIBANA_{cluster.upper()}_PORT']}"


def heap_gb():
    value = ENV["ES_HEAP"].lower()
    return float(value[:-1]) / 1024 if value.endswith("m") else float(value.rstrip("g"))
