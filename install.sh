#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ -x ".venv/bin/pip3" ]; then
    .venv/bin/pip3 install -r requirements.txt
else
    python3 -m pip install --user -r requirements.txt
fi
