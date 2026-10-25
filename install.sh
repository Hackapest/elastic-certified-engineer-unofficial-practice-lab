#!/bin/bash
# Installs and starts the lab. All logic lives in ./ece; this only makes sure
# Python is available to run it.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
  echo "Python 3.10+ is required (e.g. sudo apt install python3)." >&2
  exit 1
fi

exec python3 ./ece install "$@"
