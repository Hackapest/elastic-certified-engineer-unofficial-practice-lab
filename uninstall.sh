#!/bin/bash
# Removes the lab's containers, volumes and images. Progress in .state/ is kept.
set -e
cd "$(dirname "$0")"
exec python3 ./ece uninstall "$@"
