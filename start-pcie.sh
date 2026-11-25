#!/usr/bin/env bash
set -euo pipefail
export ESURFING_PROFILE=pcie
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if (( $# )); then
    exec ./start.sh "$@"
fi
ESURFING_PREPARE_ONLY=1 ./start.sh
exec .venv/bin/python -m esurfingpy.service start
