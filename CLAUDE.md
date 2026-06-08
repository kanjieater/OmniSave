# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Also read `.claude/CLAUDE.md` — it contains detailed rules on code style, error handling, and memory constraints that apply to all tasks.

---

## Output Style — Caveman Mode (always active)

Full spec: [`.claude/skills/caveman/SKILL.md`](.claude/skills/caveman/SKILL.md)

**Always on. Full level. No preamble. No filler. Fragments OK.**

- Drop: articles, pleasantries, hedging, trailing summaries
- Code blocks unchanged. Technical terms exact. Errors quoted exact.
- Switch level: `/caveman lite` | `/caveman ultra` | `normal mode` to exit
- Auto-clarity exception: security warnings, irreversible ops — write full prose, then resume caveman

---

## Build & Deploy

```bash
# Server lifecycle
./scripts/server.sh init          # first-time setup at OMNISAVE_ROOT
./scripts/server.sh up            # build Docker image + start detached
./scripts/server.sh logs          # follow logs
./scripts/server.sh down          # stop

# Database (SQLite inside the running container)
./scripts/db.sh                              # interactive SQLite shell (column mode, headers on)
./scripts/db.sh "SELECT * FROM devices"      # one-shot query
./scripts/db.sh < scripts/my_fix.sql         # pipe a SQL file

# Python linting / formatting (run from repo root)
ruff check server/src/            # lint (CI gate — no --fix in CI)
ruff check --fix server/src/      # lint with auto-fix
ruff format server/src/           # format

# Python tests (always run from repo root via Docker — matches CI exactly)
docker compose run --rm test                                                       # full suite + diff-cover (CI gate)
docker compose run --rm test pytest tests/test_upload.py                           # single file (no diff-cover)
docker compose run --rm test pytest tests/test_upload.py::test_commit_assembles    # single test
docker compose run --rm test pytest -k "upload"                                    # pattern match

# UI dev server (run inside server/ui/)
npm run dev                       # Vite dev server (proxies API to localhost:8991)
npm run build                     # production build → server/static/dist/
npx tsc --noEmit                  # TypeScript type-check (CI gate)
```

CI gates: ruff lint, ruff format check, tsc --noEmit, Docker smoke build, **and pytest with diff-cover** (`--fail-under=95` on lines changed vs `origin/main`). Every changed line in `server/src/` must be covered.

### Task completion checklist

| Changed files | Required steps before declaring done |
|---|---|
| `server/src/**` | 1. `docker compose run --rm test` (tests pass) → 2. `./scripts/server.sh up` (deploy) |
| `server/ui/**` | 1. `npm run build` (in `server/ui/`) → 2. `./scripts/server.sh up` (deploy) |

**Never declare any server or UI task done without running `./scripts/server.sh up`. No exceptions.**

---

## Architecture

**Server** (`server/src/`) — Python/FastAPI running in Docker. Single port (8991) only.
- `main.py` — app entry, startup wiring, SPA catch-all
- `database.py` — SQLite schema + all DB helpers; tables: `devices`, `sync_transactions`, `upload_sessions`, `upload_chunks`, `snapshot_counters`, `server_config`, `events`
- `sync_api.py` — inbound upload endpoints at `/api/v1/sync/*` (start transaction, chunk PUT, commit)
- `sync_deliver_api.py` — delivery endpoints: `/api/v1/sync/queue`, `transactions/{id}/range`, `ack`, `fail`
- `processing.py` — background PROCESSING worker: assemble chunks → SHA256 → conflict check → assign sequence → fork outbound transactions
- `db_delivery.py` — outbound delivery DB helpers; lazy peer-discovery
- `startup.py` — crash recovery on boot: expire stale uploads, fail missing archives, purge orphan chunk dirs
- `ui_api.py` — auth only (`/api/v1/ui/auth/bootstrap`, `/api/v1/ui/auth/rotate`); data endpoints deferred pending `context/server/09-ui-api.md`
- `romm_meta.py` / `titledb.py` — unused by current server; reserved for UI API phase

State machine: `UPLOADING → PROCESSING → READY_FOR_RESTORE → COMPLETED | FAILED` (+ `SUPERSEDED`)

**UI** (`server/ui/src/`) — React + TypeScript + Tailwind SPA. Vite build output goes to `server/static/dist/`.

**Production deploy** (`deploy/`) — `docker-compose.yml` and `docker-compose.no-network.yml` for production.

### Data flow (happy path — server V2 protocol)
```
Switch closes game
  → POST /api/v1/sync/transactions/inbound  → {transaction_id, session_id}
  → PUT  /api/v1/sync/sessions/{id}/chunks/{n}  (one per chunk, idempotent)
  → POST /api/v1/sync/sessions/{id}/commit       → 202 Accepted (processing async)
  → server: assemble chunks, SHA256, conflict-check, assign seq, fork outbound transactions
  → other Switch: GET /api/v1/sync/queue → pending list with total_bytes + checkpoint_ledger
  → GET  /api/v1/sync/transactions/{id}/range?offset=X&length=Y  (byte-range download)
  → POST /api/v1/sync/ack  → COMPLETED
```

### Key constraints

**Server address is never in source control.** Lives only in `.env`.

The Switch is a dumb client — no hashing, conflict resolution, or HEAD selection. All server-side.

SQLite (`sync_transactions.state`) is the absolute authority. Files on disk are untrusted shadow cache.

### Server storage layout
```
/app/data/
  staging/{session_id}/{index:010d}.bin  ← chunks during upload; deleted after processing
  archive/{transaction_id}/save.zip      ← assembled save blob (ZIP/STORE format); never deleted by server
  omnisave.db                            ← SQLite (WAL mode)
```

### Context / Specs

Design decisions, state machines, and feature specs are in `context/` — compressed for agent context windows. **Always read the relevant file(s) there before implementing any feature.**
- `context/server/` — server API, data model, reconciliation, RomM integration, UI API, auth
- `context/frontend-v2-planning/` — UI planning docs
