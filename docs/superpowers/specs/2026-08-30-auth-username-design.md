# findmy-map — username credential for the built-in login

## Summary

Extend the optional built-in login (see
`2026-08-29-optional-auth-design.md`) with a second credential: enabling
it now requires a **username and a password**, not just a password, and
the login form asks for both. This stays a single-account system — no
multi-user support is added.

## Goals

- Enabling auth from off requires both a username (any non-empty string,
  trimmed) and a password (unchanged rule: min. 8 characters).
- The login form and API (`POST /api/auth/login`) check both.
- The settings page can change the username the same way it already
  changes the password: while auth is on, changing either requires
  `current_password` and bumps `cred_version`, invalidating existing
  sessions.
- `GET /api/auth/status` exposes the current username, but **only to an
  already-authenticated caller** — it is otherwise a public,
  unauthenticated-reachable endpoint and must not leak it.
- **Backward compatible with installs that enabled auth before this
  credential existed.** Such an install has `auth_enabled=1` and a
  password but no stored username. It must keep logging in with just a
  password after the upgrade; the operator sets a username later, at
  their own pace, from the settings page.

## Non-goals (YAGNI)

Multiple accounts, username uniqueness/validation rules beyond
non-empty, a "forgot username" flow separate from the existing
`GFM_AUTH_DISABLE` escape hatch (which already resets both credentials
the same way), rate-limiting username guesses separately from the
existing per-IP password throttle.

## Architecture

No database schema change — `app_config` is already a generic key/value
table; `username` is simply a new key alongside `password`,
`auth_enabled`, `cred_version`, `session_secret`. No changes to
`service/auth.py` — the username isn't a secret, so it isn't hashed;
comparison uses `hmac.compare_digest` for consistency but this is
defense-in-depth, not a real secret comparison (there's only one
account).

Changed units:

1. `service/main.py`
   - `LoginBody` / `AuthSettingsBody` gain a `username` field.
   - `update_auth_settings`: the "enable from off" branch requires a
     username exactly like it requires a password (provided-and-valid, or
     already stored). The "already on" branch tracks
     `changing_username` alongside `changing_password`; either requires
     `current_password` and bumps `cred_version`.
   - `auth_login`: verifies the password (unchanged, constant-time,
     always run) **and** the username via `hmac.compare_digest`, ANDing
     the results without short-circuiting the slow password check first
     (no new timing side-channel). The username check auto-passes when
     nothing is stored yet — this *is* the backward-compat mechanism; it
     lives only here, not in the enable/settings logic.
   - `auth_status`: adds `"username"` to the response, gated on
     `authenticated`.
2. `web/login.html` — a username field before the password field.
3. `web/settings.html` — a username field in `#auth-fields`, prefilled
   from `/api/auth/status` on load; required (client-side) only when
   turning auth on from off, mirroring the existing password-length
   check's scoping.
4. `web/app.js` — `f_username` / `err_username_required` strings, EN+DE.
5. `service/tests/test_api.py` — `_enable_auth`/`_login` test helpers
   default to `username="admin"`; new tests for the fresh-enable
   requirement, wrong-username rejection, the backward-compat path (a
   DB poked directly to look like a pre-upgrade install), changing just
   the username, and `/api/auth/status` exposing/hiding the username.
