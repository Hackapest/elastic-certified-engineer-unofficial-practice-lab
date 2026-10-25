"""Lifecycle of the lab environment: bring-up, bootstrap, status, teardown."""

import time
from datetime import datetime, timezone

from . import client, config, docker, state

SAMPLE_DATASETS = ("flights", "ecommerce", "logs")


def wait_for(description, condition, timeout=300, interval=3):
    print(f"Waiting for {description}...", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(interval)
    raise SystemExit(f"Timed out waiting for {description}. See `docker compose logs`.")


def es_ready(cluster):
    try:
        client.es(cluster).get("/_cluster/health?wait_for_status=yellow&timeout=5s")
        return True
    except (OSError, client.HttpError):
        return False


def kibana_ready(cluster):
    try:
        status = client.kibana(cluster).get("/api/status", timeout=10)
        return status["status"]["overall"]["level"] == "available"
    except (OSError, client.HttpError, KeyError):
        return False


def load_sample_data(cluster):
    kibana = client.kibana(cluster)
    installed = {d["id"] for d in kibana.get("/api/sample_data") if d["status"] == "installed"}
    for dataset in SAMPLE_DATASETS:
        if dataset not in installed:
            print(f"  cluster {cluster.upper()}: loading sample data '{dataset}'", flush=True)
            kibana.post(f"/api/sample_data/{dataset}", timeout=300)


def bootstrap():
    """Bring a freshly started stack into its ready state. Safe to run repeatedly."""
    docker.copy_ca_cert()
    for cluster in config.CLUSTERS:
        wait_for(f"Elasticsearch cluster {cluster.upper()}", lambda: es_ready(cluster))
        client.es(cluster).post("/_security/user/kibana_system/_password",
                                {"password": config.KIBANA_SYSTEM_PASSWORD})
    for cluster in config.CLUSTERS:
        wait_for(f"Kibana {cluster.upper()}", lambda: kibana_ready(cluster))
        load_sample_data(cluster)


def up():
    print("Building and starting containers...", flush=True)
    docker.compose("build", "--quiet")
    docker.compose("up", "-d", "--quiet-pull")
    bootstrap()


def down(remove_images=False):
    args = ["down", "--volumes", "--remove-orphans"]
    if remove_images:
        args += ["--rmi", "all"]
    docker.compose(*args)


ELSER_ENDPOINT = ".elser-2-elasticsearch"


def ml_ready(cluster="a"):
    """Is the ELSER model downloaded on the cluster? (Semantic search tasks need it.)"""
    status, response = client.es(cluster).send("GET", "/_ml/trained_models/.elser_model_2*")
    return status == 200 and bool((response or {}).get("trained_model_configs"))


def ml_setup():
    """Download and start ELSER on both clusters by using its default inference endpoint once."""
    for cluster in config.CLUSTERS:
        print(f"Cluster {cluster.upper()}: preparing ELSER (the first time downloads ~270 MB)...", flush=True)
        status, response = client.es(cluster).send(
            "POST", f"/_inference/sparse_embedding/{ELSER_ENDPOINT}?timeout=600s",
            b'{"input": "test"}', "application/json", timeout=660)
        if status != 200:
            raise SystemExit(f"ELSER isn't available on cluster {cluster.upper()}: HTTP {status}: {str(response)[:300]}")
    print("ELSER is ready on both clusters. Semantic search tasks are now available.")


NODE_CONFIG = "/usr/share/elasticsearch/config/elasticsearch.yml"


def read_node_config(service):
    """elasticsearch.yml of a node, running or stopped."""
    result = docker.compose("cp", f"{service}:{NODE_CONFIG}", "-", capture=True)
    import io, tarfile   # `docker cp ... -` writes a tar stream
    with tarfile.open(fileobj=io.BytesIO(result.stdout.encode("latin-1"))) as tar:
        return tar.extractfile(tar.getmembers()[0]).read().decode()


def write_node_config(service, text):
    """Replace elasticsearch.yml of a node, running or stopped (keeps owner and permissions)."""
    import os, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "elasticsearch.yml")
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o664)
        docker.compose("cp", "--archive", path, f"{service}:{NODE_CONFIG}", capture=True)
        docker.compose("exec", "-T", "--user", "root", service, "chown", "1000:0", NODE_CONFIG,
                       check=False, capture=True)


def edit_node_config(service):
    import os, subprocess, tempfile
    original = read_node_config(service)
    with tempfile.NamedTemporaryFile("w", suffix=f"-{service}.yml", delete=False) as f:
        f.write(original)
        path = f.name
    try:
        subprocess.call([os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vim", path])
        edited = open(path).read()
    finally:
        os.unlink(path)
    if edited == original:
        print("No changes.")
        return
    write_node_config(service, edited)
    print(f"Saved. Restart the node to apply it: ./ece restart {service[3:]}  (or ./ece start {service[3:]})")


def node_service(name):
    """Accept `a2`, `es-a2`, `kibana-a` or `b` (Kibana of cluster B is `kibana-b`)."""
    if name in config.NODES or name in ("kibana-a", "kibana-b"):
        return name
    if f"es-{name}" in config.NODES:
        return f"es-{name}"
    raise SystemExit(f"Unknown node '{name}'. Use one of: "
                     f"{', '.join(n[3:] for n in config.NODES)}, kibana-a, kibana-b")


def license_summary(es):
    lic = es.get("/_license")["license"]
    if lic["type"] == "trial" and "expiry_date_in_millis" in lic:
        expiry = datetime.fromtimestamp(lic["expiry_date_in_millis"] / 1000, timezone.utc)
        days = (expiry - datetime.now(timezone.utc)).days
        return f"trial, {days} days left" if lic["status"] == "active" else "trial EXPIRED (./ece reset)"
    return lic["type"]


def status():
    running = docker.running_services()
    if not running:
        print("The lab is not running. Start it with ./install.sh")
        return
    if not config.CA_CERT.exists():
        docker.copy_ca_cert()

    for cluster in config.CLUSTERS:
        nodes = [n for n in config.NODES if n.startswith(f"es-{cluster}")]
        up_nodes = [n for n in nodes if n in running]
        print(f"Cluster {cluster.upper()} (cluster-{cluster})")
        es = client.es(cluster)
        try:
            health = es.get("/_cluster/health?timeout=5s")
            print(f"  health          {health['status']}, {health['number_of_nodes']} nodes, "
                  f"{health['unassigned_shards']} unassigned shards")
            print(f"  license         {license_summary(es)}")
        except (OSError, client.HttpError) as e:
            print(f"  health          unreachable ({e})")
        print(f"  containers up   {', '.join(n[3:] for n in up_nodes) or 'none'}")
        print(f"  Elasticsearch   {config.es_url(cluster)}")
        kibana_state = "available" if kibana_ready(cluster) else "not ready"
        print(f"  Kibana          {config.kibana_url(cluster)}  ({kibana_state})")
        print()
    ca = config.CA_CERT.relative_to(config.ROOT) if config.CA_CERT.is_relative_to(config.ROOT) else config.CA_CERT
    print(f"Login           elastic / {config.ELASTIC_PASSWORD}")
    print(f"CA certificate  {ca}  (curl --cacert {ca} -u elastic:{config.ELASTIC_PASSWORD} {config.es_url('a')})")
    from . import exam   # (exam imports lab)
    running = exam.active()
    if running:
        left = int(exam.time_left(running).total_seconds())
        when = f"{left // 3600}h {left % 3600 // 60:02d}m left" if left > 0 else "time is up: ./ece exam finish"
        print(f"\nExam running: {len(running['tasks'])} tasks, {when}. `./ece exam` for the list.")
    scenario = state.scenario()
    if scenario:
        print(f"\nActive scenario: {scenario['id']} (started {scenario['started']}). "
              f"`./ece scenario show` for its symptoms.")
