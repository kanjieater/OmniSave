# AI Agent Instructions
## 0. Output Style
* Caveman mode ALWAYS ACTIVE at full level. Rules in `.claude/skills/caveman/SKILL.md`.
* No greetings, no "I'll help you", no trailing summaries, no "In summary", no "Here's what I did".
* Bullets + code > prose. Answer = action. Fragment sentences OK.
* Exception: security warnings / irreversible ops → full prose, then resume caveman.

## 1. Documentation Protocol (The "Read First" Rule)
* **SHADOW CONTEXT:** All documentation has been compressed for your context window and stored in `./context/`. You MUST treat `./context/` as the absolute source of truth for all specifications, roadmaps, and architecture.
* Before writing code, locate the relevant compressed file in `./context/` and read it.
* You are operating in a documentation-heavy repository. Do not guess project architecture, conventions, or goals.
* Before writing any code or answering architectural questions, you MUST search and read the relevant files in `context/` (NOT any human-only directories).
* Treat `context/` as the absolute source of truth. If your pre-training conflicts with the local documentation, the local documentation wins.
* If a user asks you to implement a feature, first identify if there is a roadmap, cycle, or spec document. Read it to ensure you align with the overarching design constraints.

## 2. Tool Usage & Context Gathering
* Use `grep`, `find`, and `rg` (ripgrep) extensively to locate relevant concepts within the documentation folder before modifying system behavior.
* Do not read massive files blindly. Use `grep -n` to find relevant lines, or `cat` combined with standard bash tools to extract what you need.
* If you are unsure where a concept is documented, run a wide search across all `.md` files first.

## 3. Documentation Maintenance
* When you modify code that changes system behavior, state machines, or architecture, you MUST cross-reference the documentation folder to see if any context file is now outdated.
* If a context file is outdated due to your changes, explicitly ask the user if you should update the documentation to match the new code.

## 4. Execution Rules
* Fail fast. If you cannot find the required context in the documentation, tell the user what you searched for and ask for clarification.
* Do not hallucinate dependencies or libraries. Check the project's dependency files (e.g., `package.json`, `requirements.txt`) and the setup guides.
* Keep responses concise. Show your reasoning, execute the tools, and provide direct answers.

## 5. Code Organization & Modularity
* **Strict Size Limits:** Keep files under 300 lines. If a file grows beyond this, halt and extract logic into smaller, single-responsibility components or utility modules.
* **Componentization:** Strictly separate I/O operations (network, file system) from pure business logic (hashing, HEAD selection, clock arbitration).
* **No Monoliths:** Do not blindly append new features to the end of `main.py`. Create new files and import/include them.

## 6. Anti-Laziness & Completion Rules
* **No Placeholders:** Never write `pass`, `// TODO`, or `/* implement later */`. If you modify a function or create a file, write the complete, working implementation.
* **No Elision:** Do not use `...` to skip code when outputting text. Output exactly what needs to be changed or rely entirely on file editing tools.

## 7. Error Handling & Memory (Project Specific)
* **Fail Loudly:** Do not silently catch exceptions or swallow errors. If an operation fails, log the exact failure reason and either propagate the error or halt safely.
* **Server Constraints:** In Python, avoid loading entire save files into memory at once if they can be streamed.

## 8. Verification & Tooling
* **Mandatory Formatting:** Before finalizing a task, run `ruff format` on any Python file you modified, and `npx tsc --noEmit` after any TypeScript change.

## 9. Security & Boundary Enforcement
* **Zero-Trust Inputs:** Treat all network payloads, manifests, and incoming variables as hostile. Validate data types, lengths, and formats before processing.
* **Path Traversal Protection:** Never blindly construct file paths using raw variables. Explicitly sanitize all incoming `title_id` and `device_id` strings to ensure they only contain alphanumeric characters and cannot escape `/app/data/` using `../`.
* **SQL Injection Prevention (Python):** Never use string interpolation (f-strings or `.format()`) for SQLite queries. Always use parameterized queries (`conn.execute("...", (var,))`).
* **Credential Hygiene:** Never hardcode passwords or API keys in source code. Always read them from environment variables and never output them to the console or log files.

## 10. Production Deploy Gate

**Never pass `--prod` to `scripts/server.sh` without the user explicitly saying so in the current conversation.**

`./scripts/server.sh up` (no flag) always targets dev — safe to run. `--prod` targets the live production instance at `/mnt/srv/omnisave`. If a task requires deploying to prod, stop and ask the user first. No exceptions.

## 11. System Invariants (CI-Enforced)
1. **Server coverage:** Every changed line in `server/src/` must be covered by tests — enforced by `diff-cover --fail-under=95` in CI (`docker compose run --rm test` from repo root).
2. **Server test env:** The only valid test environment is Docker. Never run Python or pytest directly on the host.
3. **CI is the gate:** Never add git hooks (pre-commit, pre-push, commit-msg) that block or delay `git commit` or `git push`.
4. Tests should be considered early, but do not have to be written until the end.

## 12. Test Tiers — 2-Speed Feedback Loop

**Never run Python directly on the host. Always use Docker.**

| Tier | Command | Time | When to use |
|---|---|---|---|
| **1 — Fast (default)** | `docker compose run --rm test pytest --no-cov` | ~27s | After every Python change; iterate until green |
| **2 — CI gate** | `docker compose run --rm test` | ~30s | Python changes to `server/src/`; required before merge |

**Rules for Claude:**
* After editing `server/src/**` or `server/tests/**`: run Tier 1. Fix failures before proceeding.
* Do NOT declare a task done until the appropriate tier passes.
* Use `pytest -x --no-cov` during debugging — stops on first failure, fastest signal.
* Use `pytest --lf --no-cov` to rerun only the last failing tests after a fix.

**What each tier catches:**
* Tier 1: syntax errors, broken imports, logic failures (~27s)
* Tier 2: coverage gaps, schema drift, diff-cover gate (~30s)

## 13. Startup Repair Functions — Last Resort Only

`_repair_*` functions in `startup.py` run on **every boot forever**. Reserve them strictly for:
- True schema/data migrations (column additions, table restructures)
- Corruption recovery (data that cannot be prevented retroactively)
- Transforming persisted data to a new format required by updated code

**Never add a startup repair for a business-rule bug.** Fix the write path so the bug never occurs again. If a one-time cleanup is needed for an existing instance, provide a one-time admin SQL script — not permanent startup code.