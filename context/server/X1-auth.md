Single-User Session Token + Local Trust Bootstrap model fits bare-metal/Docker self-hosted. Reset flag maps to volume path (e.g., `/app/data/reset_admin.flag`), recovery trivial via CLI.

---

# OmniSave V1: UI Authentication Model (`10-ui-auth.md`)

Localized, single-tenant security model for Control Plane API.

## 1. Initial Bootstrap

* **Endpoint:** `POST /api/v1/ui/auth/bootstrap`
* **Behavior:** Active only if no admin token in config DB. Generates cryptographically secure random string.
* **Response:** `{ "admin_token": "sk_live_..." }`
* **Client Action:** Frontend stores token or server sets persistent `HttpOnly` cookie (`os_session`).

## 2. Standard Authentication

* **Mechanism:** All `/api/v1/ui/*` routes require validation.
* **Headers/Cookies:** Accepts `Authorization: Bearer <token>` (CLI/scripts) or `os_session` cookie (web dashboard).
* **Failure:** Returns `401 Unauthorized`. Frontend redirects to "Enter Admin Token" lock screen.

## 3. Emergency Recovery

* **Trigger:** Server monitors for `/config/reset_admin.flag` on host filesystem.
* **Behavior:** On detect (startup or runtime): wipes `admin_token`, invalidates sessions, deletes flag file. Re-opens `bootstrap` endpoint.

## 4. Token Rotation (Optional)

* **Endpoint:** `POST /api/v1/ui/auth/rotate`
* **Behavior:** Invalidates current token, generates new one, updates DB, issues new `HttpOnly` cookie. Force-logout stale sessions.
