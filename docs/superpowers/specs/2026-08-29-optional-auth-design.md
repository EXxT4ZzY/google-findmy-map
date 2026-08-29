# findmy-map v0.1.2 — optional built-in authentication

## Summary

Add an optional single-account login in front of the whole service, plus a
settings page where the operator can turn authentication on or off and
change the password. The header's light/dark button is replaced by a
settings gear, and both the theme and the EN/DE language controls move
onto the settings page.

This reverses the project's current posture ("no auth of any kind — you
*must* run it behind an authenticating reverse proxy"). With the new auth
enabled the operator may expose the service directly, over HTTPS.

## Goals

- A single account (fixed username, conceptually "admin" — the login form
  only asks for a password) gating every page and every API endpoint when
  enabled.
- Authentication starts **disabled**. The operator enables it on the
  settings page and sets the password there.
- The settings page can also disable authentication again and change the
  password.
- Brute-force resistance suitable for direct exposure: per-IP throttling
  with a growing cooldown, a fixed per-attempt delay, constant-time
  password verification, `Secure` session cookie.
- A documented escape hatch for a forgotten password.
- The theme and language selectors live on the settings page; the header
  carries only a gear icon.
- No new runtime dependency (stdlib `hashlib.scrypt`, `hmac`, `secrets`).

## Non-goals (YAGNI)

Multiple users or roles; a session-management / active-sessions UI;
email-based password reset; 2FA; CAPTCHA; any global account lockout that
a remote attacker could use to lock the operator out (per-IP throttling
only); "remember this device" as a concept separate from the 30-day
cookie.

## Architecture

New/changed units:

1. `service/store.py` — a new `app_config` key/value table with
   `get_config` / `set_config`, alongside the existing device-settings and
   geocode-cache tables.
2. `service/auth.py` (new) — password hashing, session-token signing, the
   in-memory login throttle. Pure functions + one small class, no I/O
   except through a passed-in store.
3. `service/main.py` — an HTTP middleware that gates requests, and the
   auth / settings endpoints.
4. `web/login.html` (new), `web/settings.html` (new).
5. `web/index.html`, `web/timeline.html` — header gear instead of the two
   toggle buttons.
6. `web/app.js` — drop the header-button wiring, expose theme/language
   setters, add the login/settings translation strings.
7. `SECURITY.md`, `README.md`, `.env.example`, `docker-compose.yml` — docs.
8. `service/tests/test_auth.py` (new) + additions to
   `service/tests/test_api.py`.

### Component 1 — `app_config` table

```sql
CREATE TABLE IF NOT EXISTS app_config (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

| key | meaning | default |
|---|---|---|
| `auth_enabled` | `"1"` when a login is required, else `"0"` | `"0"` |
| `password` | encoded hash `scrypt$<n>$<r>$<p>$<salt_hex>$<dk_hex>`; empty string until first set | `""` |
| `session_secret` | 64 hex chars from `secrets.token_hex(32)`; generated and persisted the first time it is read | generated |
| `cred_version` | integer as text; incremented on every password change | `"1"` |

`LocationStore` gains:

- `get_config(key: str, default: str | None = None) -> str | None`
- `set_config(key: str, value: str) -> None` (upsert)
- `get_config_many(keys: list[str]) -> dict[str, str]` — one `SELECT ...
  WHERE key IN (...)` for the middleware's per-request read.
- `session_secret() -> str` — returns the stored secret, generating and
  persisting one on first call.

Writes go through the same lock / error handling as the existing
`set_setting`. On a DB failure the store already falls back to an
in-memory database; auth then behaves as "freshly configured" (secret
regenerated, no password) which fails safe — login simply can't succeed
until reconfigured, and `auth_enabled` defaults to off.

### Component 2 — `service/auth.py`

```python
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1   # ~16 MiB, tune later via the encoded prefix

def hash_password(password: str) -> str
    # returns "scrypt$16384$8$1$<salt_hex>$<dk_hex>", salt = secrets.token_bytes(16)

def verify_password(password: str, encoded: str) -> bool
    # parses the encoded string, recomputes, hmac.compare_digest.
    # returns False for an empty/malformed encoded value.

def make_session_token(secret: str, cred_version: int, *, now: int | None = None) -> str
    # payload = b64url(json({"iat": now, "v": cred_version}))
    # sig     = b64url(hmac_sha256(secret, payload))
    # token   = f"{payload}.{sig}"

def parse_session_token(token: str, secret: str, cred_version: int,
                        *, max_age: int = 30*24*3600, now: int | None = None) -> bool
    # split, recompute sig, hmac.compare_digest; reject if v != cred_version
    # or now - iat > max_age or now - iat < -60 (clock skew). Returns True/False.


class LoginThrottle:
    """In-memory per-IP failed-login tracking. Process-local; resets on restart."""
    WINDOW = 15 * 60
    FREE_ATTEMPTS = 5
    COOLDOWNS = [30, 120, 600, 1800]   # seconds; last value repeats

    def retry_after(self, ip: str, *, now: float | None = None) -> int
        # 0 when a login attempt is allowed, else seconds to wait.

    def record_failure(self, ip: str, *, now: float | None = None) -> None
    def record_success(self, ip: str) -> None   # clears the IP entirely
```

The cooldown level is `max(0, failures_in_window - FREE_ATTEMPTS)`, indexed
into `COOLDOWNS` (clamped to the last entry). `retry_after` returns the
remaining time between the most recent failure and
`most_recent_failure + COOLDOWNS[level-1]`.

Client IP: `request.client.host`. If a local TLS-terminating proxy is
used, the operator runs uvicorn with `--proxy-headers
--forwarded-allow-ips=<proxy ip>` so `request.client.host` reflects the
real client (documented in `SECURITY.md`). The app itself does not parse
`X-Forwarded-For`.

### Component 3 — middleware and endpoints (`service/main.py`)

**Config knobs (env, read at startup):**

| env | default | purpose |
|---|---|---|
| `GFM_AUTH_DISABLE` | unset | when `1`/`true`, auth is forced off regardless of `app_config`; logs a warning at startup. Forgotten-password / lockout escape hatch. |
| `GFM_COOKIE_INSECURE` | unset | when `1`/`true`, the session cookie is set without `Secure` (plain-HTTP local testing only; logs a warning). |
| `GFM_LOGIN_DELAY_MS` | `500` | fixed delay applied to every login attempt. `0` in tests. |

**Middleware** — `@app.middleware("http")`, so it wraps the `StaticFiles`
mount:

```
if GFM_AUTH_DISABLE:                     -> pass through
cfg = store.get_config_many(["auth_enabled", "cred_version"])
if cfg["auth_enabled"] != "1":           -> pass through
if request.url.path in PUBLIC_PATHS:     -> pass through
token = request.cookies.get("fmm_session")
if token and parse_session_token(token, store.session_secret(),
                                 int(cfg["cred_version"])):
                                         -> pass through
if path.startswith("/api/"):            -> 401 JSON {"detail": "authentication required"}
else:                                    -> 302 to /login.html?next=<url-encoded path+query>
```

`PUBLIC_PATHS` (exact matches): `/login.html`, `/app.css`, `/app.js`,
`/favicon.ico`, `/api/auth/login`, `/api/auth/status`, `/api/auth/logout`.
These are only bypassed while auth is *enabled and the caller is
unauthenticated*; they carry no secrets (the two JS/CSS files are the same
ones the app already serves).

**Session cookie** attributes on set: `HttpOnly; Path=/; SameSite=Lax;
Max-Age=2592000` plus `Secure` unless `GFM_COOKIE_INSECURE`. Clearing
sets `Max-Age=0`.

**Endpoints:**

`GET /api/auth/status`
: `{"auth_enabled": bool, "authenticated": bool}`. `authenticated` is
  computed the same way the middleware does; it is `false` whenever
  `auth_enabled` is `false`. Always reachable.

`POST /api/auth/login` — body `{"password": str}`, `block_cross_site` dep,
`async def` (for the delay in step 2)
: 1. `ra = throttle.retry_after(ip)`; if `ra > 0` →
     `429 {"detail": "too many attempts", "retry_after": ra}`.
  2. `await asyncio.sleep(GFM_LOGIN_DELAY_MS / 1000)`.
  3. If `auth_enabled != "1"` → `400 {"detail": "authentication is disabled"}`.
  4. `verify_password(body.password, stored)`:
     - false → `throttle.record_failure(ip)` → `401 {"detail": "wrong password"}`.
     - true → `throttle.record_success(ip)`, set `fmm_session` cookie
       (`make_session_token(secret, cred_version)`), `{"ok": true}`.

`POST /api/auth/logout`
: clears the cookie, `{"ok": true}`. No-op-safe when not logged in.

`PUT /api/settings/auth` — body
`{"enabled": bool, "new_password": str | None, "current_password": str | None}`,
`block_cross_site` dep
: Let `currently_on = auth_enabled == "1"`, `has_hash = password != ""`.

  Authorisation:
  - `currently_on` → the request only reaches here with a valid session
    (middleware). Additionally, **changing the password or disabling auth
    requires `current_password` to verify**; otherwise `403 {"detail":
    "current password is incorrect"}`.
  - `not currently_on` → no session required (bootstrap).

  Transitions:
  - **enable** (`enabled` true, `currently_on` false):
    - needs a usable password: `new_password` given (≥ 8 chars) *or*
      `has_hash` already true. Missing/short → `422`.
    - if `new_password` given: `set_config("password", hash_password(new))`.
    - `set_config("auth_enabled", "1")`; increment `cred_version` on every
      enable transition (so any session issued before a previous disable
      is invalidated).
    - set the `fmm_session` cookie so the operator is immediately logged in.
  - **change password** (`enabled` true, `currently_on` true,
    `new_password` given):
    - `current_password` verified (above), `new_password` ≥ 8 → `422` if not.
    - `set_config("password", hash_password(new))`, increment
      `cred_version` (invalidates every other session), re-set this
      caller's cookie with the new version.
  - **disable** (`enabled` false, `currently_on` true):
    - `current_password` verified.
    - `set_config("auth_enabled", "0")`. The stored hash is kept, so
      re-enabling later does not force a new password.
  - no-op (`enabled` matches, no `new_password`) → `200`, nothing changes.

  Response: `{"auth_enabled": bool}`, with `Set-Cookie` when a login or
  re-issue happened.

  Password policy: minimum 8 characters, no other rule. The check lives in
  one helper so it is easy to change.

### Component 4 — `web/login.html`

Standalone page using `app.css` + `app.js` (for theme/language only).

- On load: `GET /api/auth/status`. If `!auth_enabled` or `authenticated`
  → `location.replace(next_param() or "/")`.
- A single password `<input type="password">`, a submit button, an error
  line.
- Submit → `POST /api/auth/login {password}`:
  - `200` → `location.replace(sanitised next or "/")`.
  - `401` → show "wrong password".
  - `429` → show "too many attempts, try again in N s", disable the
    button for `retry_after` seconds.
- `next` handling: read `?next=`, accept only if it starts with a single
  `/` and not `//` (local paths only), else ignore.

### Component 5 — `web/settings.html`

Reachable from the header gear on both pages. Uses `app.css` + `app.js`.

Sections, top to bottom:

1. **Language** — two options (EN / DE). Changing it calls
   `window.FindMyMap.setLang(x)` (writes `localStorage`, re-applies
   immediately). No save button.
2. **Theme** — Light / Dark, calls `window.FindMyMap.setTheme(x)`.
   No save button.
3. **Authentication** — populated from `GET /api/auth/status`:
   - a "Require login" checkbox.
   - when auth is **off**: a "Password" + "Confirm password" pair. Ticking
     the box and pressing **Save** enables auth.
   - when auth is **on**: a "Current password" field always; "New
     password" + "Confirm" for an optional change. Un-ticking the box and
     pressing **Save** (with the current password) disables auth.
   - **Save** → `PUT /api/settings/auth`. Inline messages for `403`
     (wrong current password), `422` (too short / mismatch — mismatch is
     checked client-side first), success.
   - after enabling: a note "A login is now required." (the cookie is
     already set, so the operator stays in).

A back-to-map link in the header (mirrors the timeline page).

### Component 6 — header + `app.js`

`web/index.html` and `web/timeline.html` header row:

```html
<h1>FindMy Map</h1>   <!-- "Timeline" on timeline.html -->
<a id="settings-link" class="icon-btn" href="settings.html"
   data-i18n-aria="settings" aria-label="Settings">⚙</a>
```

The `#lang-toggle` and `#theme-toggle` buttons are removed.

`web/app.js`:
- keep the synchronous `<head>` application of theme and `lang`.
- in `setup()`, remove the `#lang-toggle` / `#theme-toggle` event wiring
  and the `applyLangToggle()` call.
- guard the button updates inside `applyTheme()` with `if (btn)` (already
  partly guarded).
- expose on `window.FindMyMap`: `setTheme(t)` (wraps `applyTheme` +
  fires `onThemeChange`), `getTheme()`, `setLang(l)` (existing internal
  `setLang`), `getLang()` (exists).
- add `STRINGS.en` / `STRINGS.de` keys: `settings` (aria), page titles and
  section headings for settings.html, the field labels, the login page
  strings, and the error messages.

### Component 7 — docs

- **`SECURITY.md`** — replace the opening section. New content: findmy-map
  has an optional built-in login (single account, signed session cookie).
  - With it **enabled**, the service may be exposed directly, **but only
    over HTTPS** — the cookie is `Secure` and, without TLS, both the
    password and the cookie travel in clear. A TLS-terminating reverse
    proxy is the normal way to get HTTPS; if it runs on the same host,
    start uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>` so
    login throttling sees real client IPs.
  - With it **disabled**, the previous rule stands: run it behind an
    authenticating proxy / VPN.
  - Document `GFM_AUTH_DISABLE` (forgotten password), the per-IP throttle,
    and that the login delay is fixed at `GFM_LOGIN_DELAY_MS`.
  - Keep the existing defence-in-depth bullets; add the new ones.
- **`README.md`** — a short "Authentication" subsection under "Web UI":
  off by default, enable + set the password on the settings page (gear
  icon), `GFM_AUTH_DISABLE=1` to recover. Add `GFM_AUTH_DISABLE` to the
  env table.
- **`.env.example`** — commented `GFM_AUTH_DISABLE`, `GFM_COOKIE_INSECURE`
  (with a "local testing only" warning), `GFM_LOGIN_DELAY_MS`.
- **`docker-compose.yml`** — a commented `ports:` example with a comment
  pointing at `SECURITY.md`; the default stays proxy-net-only with no
  published port.

### Component 8 — tests

**`service/tests/test_auth.py`** (new, pure unit):
- `hash_password` / `verify_password` round-trip; wrong password → false;
  malformed / empty encoded → false.
- `make_session_token` / `parse_session_token` round-trip; tampered
  payload or signature → false; `v` mismatch → false; `iat` older than
  `max_age` → false; future `iat` beyond skew → false.
- `LoginThrottle`: allowed for the first `FREE_ATTEMPTS`; blocked
  afterwards with a growing `retry_after`; `record_success` clears the IP;
  failures outside `WINDOW` are ignored (inject `now`).

**`service/tests/test_api.py`** (extend the existing `client` fixture):
- fixture also writes `login.html` and `settings.html` stubs into
  `GFM_WEB_DIR` and sets `GFM_LOGIN_DELAY_MS=0`.
- default (auth off): every existing test still passes; `/`,
  `/api/locations` reachable with no cookie.
- `PUT /api/settings/auth {enabled:true, new_password:"secret123"}` →
  `200` + `Set-Cookie`; afterwards `GET /api/locations` with no cookie →
  `401`, `GET /` with no cookie → `302` to `/login.html`; with the cookie
  → `200`.
- `POST /api/auth/login` wrong → `401`; right → `200` + cookie; the cookie
  then opens `/api/locations`.
- repeated wrong logins → `429` with `retry_after` once over the free
  attempts.
- change password via `PUT /api/settings/auth` (with `current_password`) →
  old cookie now `401`, new cookie works.
- disable via `PUT /api/settings/auth {enabled:false, current_password}` →
  `/api/locations` reachable again with no cookie.
- `PUT /api/settings/auth` to disable with a wrong `current_password` →
  `403`.
- `monkeypatch.setenv("GFM_AUTH_DISABLE", "1")` (fresh import) with auth
  enabled in the DB → endpoints reachable with no cookie.
- allowlist: `/login.html`, `/app.js` return `200` with no cookie while
  auth is on.
- `POST /api/auth/logout` clears the cookie (response header asserts
  `Max-Age=0`).
- `block_cross_site` still applies: `PUT /api/settings/auth` with
  `sec-fetch-site: cross-site` → `403`.

## Data flow

1. Request → middleware reads `auth_enabled` (+ `cred_version`). Off →
   serve. On + valid `fmm_session` → serve. On + not → `302
   /login.html?next=…` (page) or `401` (API).
2. `login.html` → `POST /api/auth/login` → throttle + fixed delay +
   constant-time verify → `Set-Cookie fmm_session` → redirect to `next`.
3. Later requests carry the cookie; the middleware verifies HMAC +
   `cred_version` + age on each.
4. `settings.html` → `PUT /api/settings/auth` → updates `app_config`; a
   password change bumps `cred_version` and re-issues the caller's cookie.
5. Theme / language never touch the server — `settings.html` writes
   `localStorage` through `app.js`, which applies them synchronously on
   every page load.

## Error handling

| Condition | Result |
|---|---|
| Invalid / tampered / expired cookie | treated as logged out (redirect or 401) |
| Login, wrong password | `401`, per-IP failure recorded |
| Login, throttled | `429 {"detail","retry_after"}` |
| Login, auth disabled | `400` |
| Settings change, wrong `current_password` | `403` |
| Settings change, new password < 8 chars | `422` |
| Settings enable with no password and no stored hash | `422` |
| `app_config` unreadable (DB error) | store falls back to in-memory; secret regenerates, `auth_enabled` reads default off — fails safe |
| `GFM_AUTH_DISABLE=1` | middleware passes everything through; warning logged at startup |

## Migration / compatibility

- The `app_config` table is created by `executescript` on startup like the
  other tables; existing databases gain it automatically.
- Default `auth_enabled = "0"` means an upgrade changes nothing until the
  operator opts in.
- No image or compose change is required to upgrade; the new `ports:`
  block in `docker-compose.yml` is commented out.
- Version bumps to `0.1.2`; the release workflow tags the image on
  `v0.1.2`.
