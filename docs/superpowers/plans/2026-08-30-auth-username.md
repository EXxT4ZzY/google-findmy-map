# Username Credential for the Built-in Login — Implementation Plan

**Goal:** Enabling the built-in login requires a username and a password
(both required on a fresh enable); the login form and API check both; the
settings page can change either while on. Installs that already had auth
enabled before this shipped keep logging in with just a password until
the operator sets a username.

**Architecture:** No schema change — `username` is a new `app_config` key,
alongside the existing `password`/`auth_enabled`/`cred_version`. No
changes to the stdlib-crypto `auth.py` module. All logic lives in
`service/main.py`'s existing auth endpoints, plus the two auth-related
static pages.

**Spec:** `docs/superpowers/specs/2026-08-30-auth-username-design.md`

**Tech Stack:** unchanged from the original auth feature — Python 3.11,
FastAPI/Starlette, stdlib `hmac` (new import in `main.py`), vanilla JS.

## Tasks

1. **Backend — `service/main.py`**
   - `import hmac`.
   - `LoginBody.username: str = ""`, `AuthSettingsBody.username: str | None = None`.
   - `_auth_config()`'s cached fetch gains `"username"` (cheap — it's
     already TTL-cached, used by the auth gate and `/api/auth/status`).
   - `update_auth_settings`: fetch `"username"` alongside the other keys;
     mirror the password's "provided → validate+store; else require an
     already-stored one" shape for a fresh enable; for an already-enabled
     install, compute `changing_username` next to `changing_password`,
     require `current_password` if either is set, bump `cred_version` and
     re-issue the cookie if either changed.
   - `auth_login`: fetch `username` too; always run
     `auth.verify_password` (unchanged) and separately compute
     `ok_username = not stored_username or hmac.compare_digest(...)`;
     require both. This one line *is* the backward-compat guarantee.
   - `auth_status`: add `"username"` to the response only when
     `authenticated` is true.

2. **Frontend**
   - `web/login.html`: username input before the password field, sent in
     the login POST body, takes over `autofocus`.
   - `web/settings.html`: username input in `#auth-fields`, prefilled
     from `/api/auth/status` in `load()`; required client-side only when
     `!state.auth_enabled` (mirrors the existing password check's
     scoping); always sent when enabling (a resend of the unchanged
     value is a no-op server-side).
   - `web/app.js`: `f_username` / `err_username_required`, EN + DE.

3. **Tests — `service/tests/test_api.py`**
   - `_enable_auth(client, password="secret123", username="admin")`,
     `_login(client, password, username="admin")` — covers almost every
     existing test unchanged.
   - Fix the handful of raw (non-helper) calls that need an explicit
     username now: the fresh-enable test, the two recovery-flow logins,
     the forwarded-proto login.
   - Add: enable-without-username → 422; blank/whitespace username → 422;
     wrong-username-right-password → 401; changing only the username
     needs `current_password` and rotates sessions; resending the
     unchanged username is a no-op; a DB poked to look pre-upgrade
     (password set, username cleared) still logs in with any/no username;
     `/api/auth/status` carries `username` only when authenticated.

4. **Docs** — `README.md` Authentication section, `SECURITY.md`
   (description, session-token bullet, forgot-password paragraph).

## Verification

`cd findmy-map-production && .venv/bin/python -m pytest -q` — full suite
green (144 tests: 138 existing + 6 new/split out for this feature).
