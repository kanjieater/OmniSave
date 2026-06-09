# Contributing to OmniSave

## Dev Environment

```bash
# One-time setup
cp .env.example .env          # fill in OMNISAVE_ROOT and other required vars
./scripts/server.sh init      # create data dirs at OMNISAVE_ROOT

# Start / stop
./scripts/server.sh up        # build image + start detached
./scripts/server.sh logs      # follow logs
./scripts/server.sh down      # stop

# UI dev server (hot reload, proxies API to localhost:8991)
cd server/ui && npm run dev
```

## Conventional Commits

This repo uses [Conventional Commits](https://www.conventionalcommits.org/). The format
drives automatic changelog generation and version bumping via release-please.

| Prefix | Effect | Example |
|---|---|---|
| `feat:` | minor version bump | `feat: add per-device sync toggle` |
| `fix:` | patch version bump | `fix: prevent duplicate chunk upload` |
| `feat!:` or `BREAKING CHANGE:` footer | major version bump | `feat!: new sync protocol` |
| `chore:`, `docs:`, `refactor:`, `test:` | no version bump | `chore: update dependencies` |

## Issue-First Workflow

1. File an issue describing the bug or feature
2. Create a branch from the issue (GitHub's "Create a branch" button, or manually)
3. Open a PR with `Closes #N` in the description
4. All CI checks must pass before merge

## CI Requirements

All five checks must be green before a PR can merge:

| Check | Command |
|---|---|
| Python lint | `ruff check server/src/` |
| Python format | `ruff format --check server/src/` |
| TypeScript | `npx tsc --noEmit` (in `server/ui/`) |
| Python tests | `docker compose run --rm test` |
| Docker build | automated smoke build |

Run the full test suite locally before pushing:

```bash
docker compose run --rm test                               # full suite + diff-cover
docker compose run --rm test pytest --no-cov tests/        # fast iteration (no coverage)
```

## Code Style

- **Python:** ruff enforces formatting and linting. Run `ruff format server/src/ && ruff check --fix server/src/` before committing.
- **TypeScript:** strict mode, no implicit any. Run `npx tsc --noEmit` in `server/ui/`.
- **File size:** keep files under 300 lines. Extract logic into smaller modules rather than appending.
- **No silent errors:** log failures loudly; do not swallow exceptions.
- **Parameterized queries only:** never use f-strings in SQLite queries.

## PR Size Guidance

Prefer PRs under ~500 lines changed. Large diffs are hard to review and risky to merge.
If your feature requires more, split it: land the foundation first, then the feature on top.

## Release Process

Releases are fully automated:

1. Merge conventional commits to `main`
2. release-please opens a "Release PR" that bumps `VERSION`, `package.json`, `_version.py`, and `CHANGELOG.md`
3. Merge the Release PR → git tag created → GitHub Release published → Docker image pushed to GHCR

You never need to manually tag or publish. Merge the Release PR when ready to ship.
