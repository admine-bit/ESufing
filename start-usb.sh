#!/usr/bin/env bash
set -euo pipefail
export ESURFING_PROFILE=usb
exec "$(dirname -- "${BASH_SOURCE[0]}")/start.sh" "$@"
