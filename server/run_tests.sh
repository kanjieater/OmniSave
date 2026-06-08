#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
docker run --rm -v "$(pwd)":/app -w /app python:3.11-slim bash -c "
  pip install -q -r requirements.txt -r requirements-test.txt &&
  python -m pytest tests/ \"\$@\"
" -- "$@"
