"""Host checks run before installing."""

import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from . import config, docker

REQUIRED_MAP_COUNT = 262144
MAP_COUNT_FILE = Path("/proc/sys/vm/max_map_count")


def is_wsl():
    return "microsoft" in platform.uname().release.lower()


def ask(question):
    try:
        return input(f"{question} [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


def check_docker():
    if not shutil.which("docker"):
        return "Docker is not installed."
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return ("Cannot talk to the Docker daemon. Is it running, and is your user in the "
                "`docker` group? (sudo usermod -aG docker $USER, then open a new terminal)")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        return "Docker Compose v2 is missing (the docker-compose-plugin package)."
    return None


def check_map_count():
    if not MAP_COUNT_FILE.exists():  # not Linux; Docker Desktop's VM handles it
        return None
    current = int(MAP_COUNT_FILE.read_text())
    if current >= REQUIRED_MAP_COUNT:
        return None

    print(f"vm.max_map_count is {current}; Elasticsearch requires at least {REQUIRED_MAP_COUNT}.")
    if ask("Set it now with sudo (until the next reboot)?"):
        subprocess.run(["sudo", "sysctl", "-w", f"vm.max_map_count={REQUIRED_MAP_COUNT}"])
        if int(MAP_COUNT_FILE.read_text()) >= REQUIRED_MAP_COUNT:
            print("Done. To make it permanent:")
            print_map_count_persist_help()
            return None
    print_map_count_persist_help()
    return "vm.max_map_count is too low."


def print_map_count_persist_help():
    if is_wsl():
        print("  Add to %UserProfile%\\.wslconfig on Windows:\n"
              "    [wsl2]\n"
              f"    kernelCommandLine = sysctl.vm.max_map_count={REQUIRED_MAP_COUNT}\n"
              "  then run `wsl --shutdown` in PowerShell and reopen the terminal.")
    else:
        print(f"  echo 'vm.max_map_count={REQUIRED_MAP_COUNT}' | "
              "sudo tee /etc/sysctl.d/99-elasticsearch.conf && sudo sysctl --system")


def required_memory_gb():
    return 6 * (config.heap_gb() + config.ES_OFFHEAP_GB) + 2 * config.KIBANA_MEMORY_GB


def check_memory(assume_yes):
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    total_kb = int(next(l for l in meminfo.read_text().splitlines()
                        if l.startswith("MemTotal")).split()[1])
    total_gb = total_kb / 1024 / 1024
    needed = required_memory_gb()
    if total_gb >= needed:
        return None

    print(f"This machine has {total_gb:.1f} GB of memory; the lab needs about {needed:.0f} GB "
          f"with ES_HEAP={config.ENV['ES_HEAP']}.")
    if is_wsl():
        print("  WSL2 gets half of the host's memory by default. To give it more, add to\n"
              "  %UserProfile%\\.wslconfig on Windows:\n"
              "    [wsl2]\n"
              "    memory=32GB\n"
              "  then run `wsl --shutdown` in PowerShell and reopen the terminal.")
    print("  Alternatively, lower ES_HEAP in .env (e.g. ES_HEAP=512m).")
    if assume_yes or ask("Continue anyway?"):
        return None
    return "Not enough memory."


def check_ports():
    # Our own running stack holds the ports; that's fine on reinstall
    if docker.running_services():
        return None
    busy = []
    for key in ("ES_A_PORT", "ES_B_PORT", "KIBANA_A_PORT", "KIBANA_B_PORT"):
        port = int(config.ENV[key])
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                busy.append(f"{port} ({key})")
    if busy:
        return f"Ports already in use: {', '.join(busy)}. Free them or change them in .env."
    return None


def run(assume_yes=False):
    print("Checking prerequisites...")
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required.")
    error = check_docker()
    if error:
        raise SystemExit(error)
    for check in (check_map_count, lambda: check_memory(assume_yes), check_ports):
        error = check()
        if error:
            raise SystemExit(error)
    print("Prerequisites OK.")
