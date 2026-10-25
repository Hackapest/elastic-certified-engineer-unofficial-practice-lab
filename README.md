# Elastic Certified Engineer practice lab (unofficial)

Two 3-node Elasticsearch 9.3 clusters with Kibana, sample data, exam-style
tasks with automatic checking, and troubleshooting scenarios.

> 189 exam-style tasks covering every core and common topic of the exam, 13
> troubleshooting scenarios and a timed exam mode. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Requirements

- Docker Engine with Docker Compose v2
- Python 3.10+
- About 14 GB of free memory (more if you raise `ES_HEAP` in `.env`)
- `vm.max_map_count` of at least 262144 (the installer checks and explains how to set it)

## Install

```bash
git clone https://github.com/Hackapest/elastic-certified-engineer-unofficial-practice-lab.git
cd elastic-certified-engineer-unofficial-practice-lab
./install.sh
```

This builds the image, generates certificates, starts both clusters and both
Kibanas, and loads the sample data. It takes a few minutes the first time.

| | Cluster A | Cluster B |
|---|---|---|
| Elasticsearch | https://localhost:9200 | https://localhost:9201 |
| Kibana | http://localhost:5601 | http://localhost:5602 |

Login: `elastic` / `elastic-lab` (set in `.env`).

## Practising

```bash
./ece next            # get a task you haven't passed yet
                      # ...solve it in Kibana Dev Tools (http://localhost:5601)...
./ece answer          # query tasks: hand in your request, as written in Dev Tools
./ece check           # grade it
./ece solution        # stuck? see the reference solution
./ece progress        # what you've done per exam topic
./ece scenario start  # a broken cluster to diagnose and fix
./ece exam start      # a timed practice exam: 10 tasks in 3 hours, graded at the end
./ece ml-setup        # optional: ELSER for the semantic search tasks (~270 MB download)
```

Don't read `tasks/` and `scenarios/` if you want to avoid spoilers.

## Commands

```bash
./ece help            # all commands; ./ece help <command> for details
./ece status          # health, license days left, URLs, credentials
./ece shell a2        # shell into a node (a1..a3, b1..b3, kibana-a, kibana-b)
./ece config a2       # edit a node's elasticsearch.yml (also when the node is stopped)
./ece restart a2      # also: stop, start
./ece reset           # wipe everything and rebuild from scratch (~3 minutes)
./uninstall.sh        # remove containers, volumes and images
```

From the host, with curl:

```bash
curl --cacert .state/ca.crt -u elastic:elastic-lab https://localhost:9200
```

## License and disclaimer

MIT, see [LICENSE](LICENSE).

This is an independent study project. It is not affiliated with, endorsed by or sponsored by
Elastic N.V. "Elastic", "Elasticsearch", "Kibana" and "Elastic Certified Engineer" are
trademarks of Elastic N.V. The lab doesn't include Elastic software or data: Docker downloads
the official Elasticsearch and Kibana images, which are under Elastic's own licenses, and the
sample data comes from Kibana.
