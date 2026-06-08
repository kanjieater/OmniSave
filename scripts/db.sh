#!/usr/bin/env bash
# db.sh — Run SQLite commands against the live OmniSave database.
#
# Usage:
#   ./scripts/db.sh                        # interactive SQLite shell
#   ./scripts/db.sh "SELECT * FROM devices"  # one-shot query
#   ./scripts/db.sh < file.sql             # pipe a SQL file

set -euo pipefail

DB=/app/data/omnisave.db

if [ $# -eq 0 ] && [ -t 0 ]; then
  # Interactive shell
  docker exec -it omnisave sqlite3 "$DB" \
    -cmd ".headers on" \
    -cmd ".mode column" \
    -cmd ".nullvalue NULL"
elif [ $# -gt 0 ]; then
  # One-shot query passed as argument
  docker exec omnisave sqlite3 "$DB" \
    -cmd ".headers on" \
    -cmd ".mode column" \
    -cmd ".nullvalue NULL" \
    "$1"
else
  # Pipe SQL from stdin
  docker exec -i omnisave sqlite3 "$DB" \
    -cmd ".headers on" \
    -cmd ".mode column" \
    -cmd ".nullvalue NULL"
fi
