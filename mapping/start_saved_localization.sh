#!/usr/bin/env bash
# Compatibility entry point: automatically locate on the saved map using AMCL.
set -eo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/mapping/start_auto_localization.sh" "${1:-c3c666243fd2}"
