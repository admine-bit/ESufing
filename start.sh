#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import click, psutil, rich, rsa, requests, dns; import importlib.util; assert importlib.util.find_spec("ddddocr")' >/dev/null 2>&1; then
    .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python build_crypto.py
if [[ "${ESURFING_PREPARE_ONLY:-0}" == "1" ]]; then
    exit 0
fi
exec .venv/bin/python main.py "$@"
