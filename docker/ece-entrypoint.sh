#!/bin/bash
# Installs this node's elasticsearch.yml on the container's first start, then
# hands over to the stock entrypoint. Later edits made inside the container
# survive restarts; recreating the container (reset) brings back the original.
set -e

config_dir=/usr/share/elasticsearch/config
marker=$config_dir/.ece-initialized

if [ ! -f "$marker" ]; then
  cp "/usr/share/elasticsearch/ece-config/${NODE_NAME}.yml" "$config_dir/elasticsearch.yml"
  touch "$marker"
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
