"""Thin wrapper around `docker compose` for this project."""

import subprocess

from . import config


def compose(*args, check=True, capture=False):
    cmd = ["docker", "compose", "--project-directory", str(config.ROOT), *args]
    result = subprocess.run(cmd, check=False, text=True,
                            capture_output=capture)
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip() if capture else ""
        raise SystemExit(f"docker compose {' '.join(args)} failed. {detail}".rstrip())
    return result


def running_services():
    result = compose("ps", "--status", "running", "--services", check=False, capture=True)
    return set(result.stdout.split()) if result.returncode == 0 else set()


def copy_ca_cert():
    config.STATE_DIR.mkdir(exist_ok=True)
    compose("cp", "es-a1:/usr/share/elasticsearch/config/certs/ca/ca.crt", str(config.CA_CERT),
            capture=True)
