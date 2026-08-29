# Optional Built-in Authentication — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional single-account login in front of the whole service, plus a settings page to toggle it and change the password, and move the theme/language controls off the header behind a settings gear.

**Architecture:** A Starlette HTTP middleware in `main.py` gates every request when auth is enabled; credentials and session secret live in a new `app_config` key/value table in the existing SQLite store; sessions are stateless HMAC-signed cookies verified against a `cred_version` counter. A new `auth.py` module holds the crypto and an in-memory per-IP login throttle. Two new static pages (`login.html`, `settings.html`) drive the flow; the map/timeline headers lose their two toggle buttons and gain a gear link.

**Tech Stack:** Python 3.11, FastAPI + Starlette, uvicorn, SQLite (stdlib `sqlite3`), stdlib `hashlib.scrypt` / `hmac` / `secrets` (no new dependency), vanilla JS + Leaflet frontend, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-optional-auth-design.md`

## Global Constraints

- No new runtime dependency — password hashing uses stdlib `hashlib.scrypt`; tokens use stdlib `hmac`/`secrets`/`base64`/`json`.
- Authentication defaults to **disabled**; an upgrade of an existing install must change nothing until the operator opts in.
- Password minimum length: **8** characters. No other password rule.
- Session cookie name: `fmm_session`. Attributes: `HttpOnly; Path=/; SameSite=Lax; Max-Age=2592000` (30 days), plus `Secure` **only** when the request is HTTPS (`request.headers.get("x-forwarded-proto", request.url.scheme)`, first comma-token).
- `GFM_AUTH_DISABLE=1` (or `true`/`yes`) forces auth off regardless of the DB.
- `GFM_LOGIN_DELAY_MS` (default `500`) is the fixed per-attempt login delay; tests set it to `0`.
- Follow existing code style: 4-space indent, `log = logging.getLogger("findmy-map")`, sqlite writes wrapped in the store's `try/except sqlite3.Error` + `_write_warned` pattern, endpoints are plain `def` unless they need `await`.
- Frontend: keep the synchronous `<head>` theme/lang application in `app.js` (no flash on load). Theme + language stay in `localStorage` — never sent to the server.
- Commit after every task with a `feat:` / `test:` / `docs:` prefixed message.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `service/auth.py` | Create | `hash_password`, `verify_password`, `make_session_token`, `parse_session_token`, `LoginThrottle` |
| `service/store.py` | Modify | `app_config` table + `get_config` / `get_config_many` / `set_config` / `session_secret` |
| `service/main.py` | Modify | env knobs, auth helpers, auth-gate middleware, `/api/auth/*` and `/api/settings/auth` endpoints |
| `web/login.html` | Create | Password login page |
| `web/settings.html` | Create | Settings page: language, theme, authentication |
| `web/index.html` | Modify | Header: gear link instead of the two toggle buttons |
| `web/timeline.html` | Modify | Same header change |
| `web/app.js` | Modify | Drop header-button wiring; expose `setTheme`/`getTheme`/`setLang`; new translation strings |
| `web/app.css` | Modify | Styles for the standalone login/settings pages; drop the dead `#lang-toggle` rule |
| `service/tests/test_auth.py` | Create | Unit tests for `auth.py` |
| `service/tests/test_store.py` | Modify | Tests for the config methods |
| `service/tests/test_api.py` | Modify | Fixture refactor + auth/settings endpoint + gating tests |
| `SECURITY.md` | Modify | Rewrite the opening "no auth" section |
| `README.md` | Modify | New "Authentication" subsection; `GFM_AUTH_DISABLE` in the env table |
| `.env.example` | Modify | Commented `GFM_AUTH_DISABLE`, `GFM_LOGIN_DELAY_MS` |
| `docker-compose.yml` | Modify | Commented `ports:` example; bump image tag to `0.1.2` |

---

## Task 1: `app_config` table and store methods

**Files:**
- Modify: `service/store.py` (schema string near line 20-44; new methods after `get_settings` ~line 138; `import secrets` near line 12)
- Test: `service/tests/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `LocationStore.get_config(key: str, default: str | None = None) -> str | None`
  - `LocationStore.get_config_many(keys: list[str]) -> dict[str, str]` (missing keys absent from the dict)
  - `LocationStore.set_config(key: str, value: str) -> None` (upsert)
  - `LocationStore.session_secret() -> str` (64 hex chars; generated + persisted on first call, stable after)

- [ ] **Step 1: Write the failing tests**

Add to `service/tests/test_store.py` (the file already has a `store` fixture yielding a `LocationStore` on a tmp path):

```python
class TestConfig:
    def test_set_then_get_roundtrip(self, store):
        store.set_config("auth_enabled", "1")
        assert store.get_config("auth_enabled") == "1"

    def test_get_missing_returns_default(self, store):
        assert store.get_config("missing") is None
        assert store.get_config("missing", "0") == "0"

    def test_set_config_overwrites(self, store):
        store.set_config("k", "a")
        store.set_config("k", "b")
        assert store.get_config("k") == "b"

    def test_get_config_many_returns_only_present_keys(self, store):
        store.set_config("a", "1")
        store.set_config("b", "2")
        assert store.get_config_many(["a", "b", "c"]) == {"a": "1", "b": "2"}

    def test_session_secret_is_generated_and_stable(self, store):
        s = store.session_secret()
        assert isinstance(s, str) and len(s) == 64
        assert store.session_secret() == s
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest service/tests/test_store.py::TestConfig -q`
Expected: FAIL — `AttributeError: 'LocationStore' object has no attribute 'set_config'`

- [ ] **Step 3: Add the schema table**

In `service/store.py`, inside the `_SCHEMA` triple-quoted string (after the `geocode_cache` table, before the closing `"""`), add:

```sql

CREATE TABLE IF NOT EXISTS app_config (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

- [ ] **Step 4: Add `import secrets`**

At the top of `service/store.py`, add `import secrets` to the import block (alphabetical order: after `import sqlite3`... actually after `import logging`; place it as `import secrets` on its own line with the others).

- [ ] **Step 5: Add the methods**

In `service/store.py`, immediately after the `get_settings` method (before the `# -- reverse-geocode cache` comment), add:

```python
    # -- application config (auth) ---------------------------------------

    def get_config(self, key, default=None):
        """Value for a config key, or ``default`` if it is not set."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM app_config WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row is not None else default

    def get_config_many(self, keys):
        """``{key: value}`` for the given keys that are set (missing keys omitted)."""
        if not keys:
            return {}
        placeholders = ",".join("?" * len(keys))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT key, value FROM app_config WHERE key IN ({placeholders})",
                tuple(keys),
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def set_config(self, key, value):
        """Upsert one config key."""
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO app_config (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = ?",
                    (key, value, value),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                if not self._write_warned:
                    log.warning("Could not write app config: %s", exc)
                    self._write_warned = True

    def session_secret(self):
        """The HMAC secret for session tokens; generated and stored on first use."""
        secret = self.get_config("session_secret")
        if not secret:
            secret = secrets.token_hex(32)
            self.set_config("session_secret", secret)
        return secret
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest service/tests/test_store.py -q`
Expected: PASS (the new `TestConfig` class and all existing store tests)

- [ ] **Step 7: Commit**

```bash
git add service/store.py service/tests/test_store.py
git commit -m "feat: app_config key/value table in the location store"
```

---

## Task 2: `auth.py` — password hashing and session tokens

**Files:**
- Create: `service/auth.py`
- Test: `service/tests/test_auth.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `hash_password(password: str) -> str` → `"scrypt$<n>$<r>$<p>$<salt_hex>$<dk_hex>"`
  - `verify_password(password: str, encoded: str) -> bool` (constant-time; `False` for empty/malformed `encoded`)
  - `make_session_token(secret: str, cred_version: int, *, now: int | None = None) -> str`
  - `parse_session_token(token: str, secret: str, cred_version: int, *, max_age: int = 2592000, now: int | None = None) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `service/tests/test_auth.py`:

```python
from auth import (hash_password, verify_password,
                  make_session_token, parse_session_token)


def test_hash_verify_roundtrip():
    enc = hash_password("correct horse")
    assert verify_password("correct horse", enc) is True
    assert verify_password("wrong", enc) is False


def test_verify_rejects_empty_or_malformed():
    assert verify_password("x", "") is False
    assert verify_password("x", "not-a-hash") is False
    assert verify_password("x", "bcrypt$1$2$3$4$5") is False
    assert verify_password("x", "scrypt$16384$8$1$zz$zz") is False


def test_token_roundtrip():
    tok = make_session_token("s3cr3t", 1, now=1000)
    assert parse_session_token(tok, "s3cr3t", 1, now=1000) is True


def test_token_rejects_tampering_and_wrong_secret():
    tok = make_session_token("s3cr3t", 1, now=1000)
    assert parse_session_token(tok + "x", "s3cr3t", 1, now=1000) is False
    assert parse_session_token(tok, "other", 1, now=1000) is False
    assert parse_session_token("no-dot", "s3cr3t", 1, now=1000) is False


def test_token_rejects_wrong_cred_version():
    tok = make_session_token("s3cr3t", 1, now=1000)
    assert parse_session_token(tok, "s3cr3t", 2, now=1000) is False


def test_token_expiry_and_clock_skew():
    tok = make_session_token("s3cr3t", 1, now=1000)
    assert parse_session_token(tok, "s3cr3t", 1, now=1000 + 29 * 86400) is True
    assert parse_session_token(tok, "s3cr3t", 1, now=1000 + 31 * 86400) is False
    assert parse_session_token(tok, "s3cr3t", 1, now=500) is False  # "issued in the future"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest service/tests/test_auth.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth'`

- [ ] **Step 3: Write `service/auth.py` (this half)**

```python
"""Password hashing and signed session tokens for the optional built-in
authentication (see SECURITY.md and the design spec).

Standard library only: scrypt, hmac, secrets, base64, json.
"""

import hashlib
import hmac
import json
import math
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_DKLEN = 32

_SESSION_MAX_AGE = 30 * 24 * 3600
_CLOCK_SKEW = 60


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, maxmem=_SCRYPT_MAXMEM, dklen=_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, dk_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
        if not expected:
            return False
    except (ValueError, AttributeError):
        return False
    try:
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=salt,
            n=int(n), r=int(r), p=int(p), maxmem=_SCRYPT_MAXMEM, dklen=len(expected),
        )
    except ValueError:
        return False
    return hmac.compare_digest(dk, expected)


def _b64(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    return urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), payload.encode("ascii"),
                         hashlib.sha256).digest())


def make_session_token(secret: str, cred_version: int, *, now: int | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = _b64(json.dumps({"iat": issued, "v": int(cred_version)},
                              separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_sign(secret, payload)}"


def parse_session_token(token: str, secret: str, cred_version: int, *,
                        max_age: int = _SESSION_MAX_AGE, now: int | None = None) -> bool:
    try:
        payload, sig = token.split(".", 1)
    except (ValueError, AttributeError):
        return False
    if not hmac.compare_digest(sig, _sign(secret, payload)):
        return False
    try:
        data = json.loads(_unb64(payload))
        iat = int(data["iat"])
        version = int(data["v"])
    except (ValueError, KeyError, TypeError):
        return False
    if version != int(cred_version):
        return False
    age = int(now if now is not None else time.time()) - iat
    return -_CLOCK_SKEW <= age <= max_age
```

(`import math` is unused here but needed by Task 3 in the same file — keep it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest service/tests/test_auth.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/auth.py service/tests/test_auth.py
git commit -m "feat: password hashing and signed session tokens (auth.py)"
```

---

## Task 3: `auth.py` — `LoginThrottle`

**Files:**
- Modify: `service/auth.py` (append the class)
- Test: `service/tests/test_auth.py` (append tests)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `LoginThrottle()` with class attrs `WINDOW = 900`, `FREE_ATTEMPTS = 5`, `COOLDOWNS = (30, 120, 600, 1800)`
  - `.retry_after(ip: str, *, now: float | None = None) -> int` — `0` when a login attempt is allowed, else seconds to wait
  - `.record_failure(ip: str, *, now: float | None = None) -> None`
  - `.record_success(ip: str) -> None` — clears the IP entirely

- [ ] **Step 1: Write the failing tests**

Append to `service/tests/test_auth.py`:

```python
from auth import LoginThrottle


def test_throttle_allows_the_free_attempts_then_blocks():
    tr = LoginThrottle()
    for _ in range(LoginThrottle.FREE_ATTEMPTS):
        assert tr.retry_after("10.0.0.1", now=0) == 0
        tr.record_failure("10.0.0.1", now=0)
    assert tr.retry_after("10.0.0.1", now=0) > 0


def test_throttle_first_cooldown_is_the_first_tier():
    tr = LoginThrottle()
    for _ in range(LoginThrottle.FREE_ATTEMPTS):
        tr.record_failure("10.0.0.1", now=0)
    # exactly FREE_ATTEMPTS failures -> first tier, not a jump to the top
    assert tr.retry_after("10.0.0.1", now=0) == LoginThrottle.COOLDOWNS[0]


def test_throttle_cooldown_is_monotonic_across_the_boundary():
    tr = LoginThrottle()
    seen = []
    for _ in range(LoginThrottle.FREE_ATTEMPTS + 5):
        tr.record_failure("10.0.0.1", now=0)
        seen.append(tr.retry_after("10.0.0.1", now=0))
    assert seen == sorted(seen)          # never decreases
    assert seen[-1] == LoginThrottle.COOLDOWNS[-1]  # clamps at the top tier


def test_throttle_success_clears_the_ip():
    tr = LoginThrottle()
    for _ in range(6):
        tr.record_failure("10.0.0.1", now=0)
    assert tr.retry_after("10.0.0.1", now=1) > 0
    tr.record_success("10.0.0.1")
    assert tr.retry_after("10.0.0.1", now=1) == 0


def test_throttle_forgets_old_failures():
    tr = LoginThrottle()
    for _ in range(6):
        tr.record_failure("10.0.0.1", now=0)
    assert tr.retry_after("10.0.0.1", now=LoginThrottle.WINDOW + 1) == 0


def test_throttle_is_per_ip():
    tr = LoginThrottle()
    for _ in range(6):
        tr.record_failure("10.0.0.1", now=0)
    assert tr.retry_after("10.0.0.2", now=0) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest service/tests/test_auth.py -k throttle -q`
Expected: FAIL — `ImportError: cannot import name 'LoginThrottle'`

- [ ] **Step 3: Append the class to `service/auth.py`**

```python
class LoginThrottle:
    """Process-local per-IP failed-login tracking. Resets on restart."""

    WINDOW = 15 * 60
    FREE_ATTEMPTS = 5
    COOLDOWNS = (30, 120, 600, 1800)  # seconds; the last value repeats

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}

    def _recent(self, ip: str, now: float) -> list[float]:
        times = [t for t in self._fails.get(ip, []) if now - t < self.WINDOW]
        if times:
            self._fails[ip] = times
        else:
            self._fails.pop(ip, None)
        return times

    def retry_after(self, ip: str, *, now: float | None = None) -> int:
        now = time.time() if now is None else now
        times = self._recent(ip, now)
        level = len(times) - self.FREE_ATTEMPTS
        if level < 0:
            return 0
        # level 0 == FREE_ATTEMPTS failures -> first cooldown tier (30 s);
        # clamp to the last tier once level exceeds the table.
        cooldown = self.COOLDOWNS[min(level, len(self.COOLDOWNS) - 1)]
        return max(0, math.ceil(times[-1] + cooldown - now))

    def record_failure(self, ip: str, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._fails.setdefault(ip, []).append(now)

    def record_success(self, ip: str) -> None:
        self._fails.pop(ip, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest service/tests/test_auth.py -q`
Expected: PASS (all `auth` tests)

- [ ] **Step 5: Commit**

```bash
git add service/auth.py service/tests/test_auth.py
git commit -m "feat: per-IP login throttle (auth.LoginThrottle)"
```

---

## Task 4: Auth-gate middleware and helpers in `main.py`

**Files:**
- Modify: `service/main.py` (imports ~line 1-27; env block ~line 34-45; helpers after `block_cross_site` ~line 110; middleware after `app = FastAPI(...)` ~line 95; lifespan ~line 88)
- Test: `service/tests/test_api.py` (refactor the `client` fixture; add gating tests)

**Interfaces:**
- Consumes: `auth.parse_session_token`, `LocationStore.get_config_many`, `LocationStore.session_secret` (Tasks 1-2).
- Produces (module-level names later tasks use):
  - `SESSION_COOKIE = "fmm_session"`
  - `AUTH_DISABLED: bool`, `LOGIN_DELAY_SECONDS: float`
  - `_login_throttle: auth.LoginThrottle`
  - `PUBLIC_PATHS: set[str]`
  - `request_is_https(request: Request) -> bool`
  - `_client_ip(request: Request) -> str`
  - `_token_ok(request: Request, cfg: dict) -> bool` — `cfg` must contain `cred_version`
  - `_set_session_cookie(response: Response, request: Request) -> None`

- [ ] **Step 1: Refactor the test fixture**

In `service/tests/test_api.py`, replace the existing `client` fixture with a builder plus two fixtures:

```python
def _build_client(tmp_path, monkeypatch, env=None):
    stub = types.ModuleType("locations")
    stub.poll_all_devices = lambda: []
    monkeypatch.setitem(sys.modules, "locations", stub)
    monkeypatch.setenv("GFM_HISTORY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("GFM_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setenv("GFM_WEB_DIR", str(tmp_path))
    monkeypatch.setenv("GFM_NOMINATIM_URL", "")   # no network in tests
    monkeypatch.setenv("GFM_LOGIN_DELAY_MS", "0")
    for name, content in (
        ("index.html", "<html>index</html>"),
        ("login.html", "<html>login</html>"),
        ("settings.html", "<html>settings</html>"),
        ("app.js", "// app"),
        ("app.css", "/* css */"),
    ):
        (tmp_path / name).write_text(content)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)

    for mod in ("main", "auth", "augment", "store", "colors", "visits", "geocode"):
        monkeypatch.delitem(sys.modules, mod, raising=False)
    import main

    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    c._main = main
    return c


@pytest.fixture
def client(tmp_path, monkeypatch):
    c = _build_client(tmp_path, monkeypatch)
    with c:
        yield c


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    """Build extra clients sharing this test's tmp DB (e.g. with different env)."""
    def _make(**env):
        return _build_client(tmp_path, monkeypatch, env)
    return _make
```

Add a small helper near the top of the file's test helpers:

```python
def _enable_auth(client, password="secret123"):
    r = client.put("/api/settings/auth", json={"enabled": True, "new_password": password})
    assert r.status_code == 200
    return r


def _login(client, password):
    return client.post("/api/auth/login", json={"password": password})
```

- [ ] **Step 2: Write the failing gating tests**

Append to `service/tests/test_api.py`:

```python
class TestAuthGate:
    def test_auth_is_off_by_default(self, client):
        assert client.get("/api/locations").status_code == 200
        assert client.get("/", follow_redirects=False).status_code == 200

    def test_enabling_auth_gates_api_and_pages(self, client):
        _enable_auth(client)                       # PUT response sets the cookie
        assert client.get("/api/locations").status_code == 200
        client.cookies.clear()
        assert client.get("/api/locations").status_code == 401
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302 and "/login.html" in r.headers["location"]

    def test_allowlisted_paths_reachable_while_locked(self, client):
        _enable_auth(client)
        client.cookies.clear()
        assert client.get("/login.html").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/api/auth/status").status_code == 200

    def test_auth_disable_env_overrides_the_db(self, make_client):
        c1 = make_client()
        with c1:
            _enable_auth(c1)
        c2 = make_client(GFM_AUTH_DISABLE="1")
        with c2:
            c2.cookies.clear()
            assert c2.get("/api/locations").status_code == 200
```

These reference `/api/settings/auth`, `/api/auth/status`, `/api/auth/login` which arrive in Tasks 5-6 — so also add a temporary shim expectation: run only `test_auth_is_off_by_default` now.

- [ ] **Step 3: Run the one test that can pass now**

Run: `python -m pytest service/tests/test_api.py::TestAuthGate::test_auth_is_off_by_default -q`
Expected: FAIL first (middleware not added; but with auth off it may already pass — if it passes, that is fine, it confirms the fixture refactor didn't break anything). Then after Step 4-6 it must still pass. The other three `TestAuthGate` tests are expected to error until Tasks 5-6 add the endpoints; that is acceptable within this task — they are re-run green at the end of Task 6.

- [ ] **Step 4: Add imports and env knobs to `main.py`**

In the stdlib import block (top of `service/main.py`), add `import asyncio`.
In the FastAPI import line (`from fastapi import Depends, FastAPI, HTTPException, Request`), add `Response`:
```python
from fastapi import Depends, FastAPI, HTTPException, Request, Response
```
Add to the `from fastapi.responses import JSONResponse` line:
```python
from fastapi.responses import JSONResponse, RedirectResponse
```
Add `from urllib.parse import quote` to the stdlib imports.
In the local-module import block (with `import colors` etc.), add `import auth`.

After the existing env block (after `VISIT_MIN_SECONDS = ...`, ~line 43), add:

```python
AUTH_DISABLED = os.environ.get("GFM_AUTH_DISABLE", "").strip().lower() in ("1", "true", "yes")
LOGIN_DELAY_SECONDS = int(os.environ.get("GFM_LOGIN_DELAY_MS", "500")) / 1000
```

- [ ] **Step 5: Add helpers and the middleware**

After the `block_cross_site` function (~line 110), add:

```python
SESSION_COOKIE = "fmm_session"
PASSWORD_MIN_LENGTH = 8
PUBLIC_PATHS = {
    "/login.html", "/app.css", "/app.js", "/favicon.ico",
    "/api/auth/login", "/api/auth/status", "/api/auth/logout",
}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def request_is_https(request: Request) -> bool:
    xfp = request.headers.get("x-forwarded-proto")
    scheme = xfp.split(",")[0].strip() if xfp else request.url.scheme
    return scheme == "https"


def _token_ok(request: Request, cfg: dict) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    return auth.parse_session_token(
        token, _store.session_secret(), int(cfg.get("cred_version") or "1")
    )


def _set_session_cookie(response: Response, request: Request) -> None:
    version = int(_store.get_config("cred_version", "1"))
    token = auth.make_session_token(_store.session_secret(), version)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=30 * 24 * 3600, httponly=True,
        samesite="lax", secure=request_is_https(request), path="/",
    )
```

Immediately after `app = FastAPI(lifespan=lifespan)` (~line 95), add:

```python
_login_throttle = auth.LoginThrottle()


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    if AUTH_DISABLED:
        return await call_next(request)
    cfg = _store.get_config_many(["auth_enabled", "cred_version"])
    if cfg.get("auth_enabled") != "1":
        return await call_next(request)
    path = request.url.path
    if path in PUBLIC_PATHS or _token_ok(request, cfg):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    query = f"?{request.url.query}" if request.url.query else ""
    nxt = quote(path + query, safe="")
    return RedirectResponse(f"/login.html?next={nxt}", status_code=302)
```

In `lifespan` (the `async def lifespan` function ~line 88), add a line at the top of the function body so the session secret exists before the first authenticated request and a warning is logged when the escape hatch is active:

```python
async def lifespan(_app):
    _store.session_secret()  # ensure it exists before any request
    if AUTH_DISABLED:
        log.warning("GFM_AUTH_DISABLE is set -- built-in authentication is OFF.")
    threading.Thread(target=_poll_loop, daemon=True).start()
    _geocoder.start()
    yield
    _geocoder.stop()
```

- [ ] **Step 6: Run the gating test + the full suite**

Run: `python -m pytest service/tests/test_api.py::TestAuthGate::test_auth_is_off_by_default service/tests/test_store.py service/tests/test_auth.py -q`
Expected: PASS. (The three endpoint-dependent `TestAuthGate` tests stay red until Task 6.)

- [ ] **Step 7: Commit**

```bash
git add service/main.py service/tests/test_api.py
git commit -m "feat: auth-gate middleware and session cookie helpers"
```

---

## Task 5: `/api/auth/status`, `/api/auth/login`, `/api/auth/logout`

**Files:**
- Modify: `service/main.py` (add endpoints; a `LoginBody` model near `DeviceSettingsBody` ~line 134)
- Test: `service/tests/test_api.py`

**Interfaces:**
- Consumes: Task 4 helpers, `auth.verify_password`, `_login_throttle`, `LOGIN_DELAY_SECONDS`.
- Produces:
  - `GET /api/auth/status` → `{"auth_enabled": bool, "authenticated": bool}`
  - `POST /api/auth/login` (`{"password": str}`) → `200 {"ok": true}` + `Set-Cookie`; `401 {"detail":"wrong password"}`; `429 {"detail":"too many attempts","retry_after": int}`; `400` when auth disabled
  - `POST /api/auth/logout` → `200 {"ok": true}`, clears the cookie

- [ ] **Step 1: Write the failing tests**

Append to `service/tests/test_api.py`:

```python
class TestAuthEndpoints:
    def test_status_reports_disabled(self, client):
        body = client.get("/api/auth/status").json()
        assert body == {"auth_enabled": False, "authenticated": False}

    def test_status_reports_enabled_and_authenticated(self, client):
        _enable_auth(client)
        body = client.get("/api/auth/status").json()
        assert body["auth_enabled"] is True and body["authenticated"] is True
        client.cookies.clear()
        body2 = client.get("/api/auth/status").json()
        assert body2["auth_enabled"] is True and body2["authenticated"] is False

    def test_login_wrong_then_right(self, client):
        _enable_auth(client, "hunter2222")
        client.cookies.clear()
        assert _login(client, "nope").status_code == 401
        r = _login(client, "hunter2222")
        assert r.status_code == 200
        assert client.get("/api/locations").status_code == 200

    def test_login_when_disabled_is_400(self, client):
        assert _login(client, "whatever").status_code == 400

    def test_login_throttles_after_free_attempts(self, client):
        _enable_auth(client)
        client.cookies.clear()
        for _ in range(5):
            assert _login(client, "wrong").status_code == 401
        r = _login(client, "wrong")
        assert r.status_code == 429
        assert r.json()["retry_after"] > 0
        assert r.headers["retry-after"]

    def test_logout_clears_the_cookie(self, client):
        _enable_auth(client)
        r = client.post("/api/auth/logout")
        assert r.status_code == 200
        set_cookie = r.headers.get("set-cookie", "").lower()
        assert "fmm_session=" in set_cookie
        assert 'max-age=0' in set_cookie or '01 jan 1970' in set_cookie

    def test_secure_flag_follows_forwarded_proto(self, client):
        _enable_auth(client)
        client.cookies.clear()
        r = _login(client, "secret123")
        assert "secure" not in r.headers["set-cookie"].lower()
        client.cookies.clear()
        r2 = client.post("/api/auth/login", json={"password": "secret123"},
                         headers={"x-forwarded-proto": "https"})
        assert "secure" in r2.headers["set-cookie"].lower()

    def test_login_blocks_cross_site(self, client):
        _enable_auth(client)
        client.cookies.clear()
        r = client.post("/api/auth/login", json={"password": "secret123"},
                        headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest service/tests/test_api.py::TestAuthEndpoints -q`
Expected: FAIL — 404s / assertion errors (endpoints not defined)

- [ ] **Step 3: Add the `LoginBody` model and the endpoints**

Near `class DeviceSettingsBody` (~line 134) in `service/main.py`, add:

```python
class LoginBody(BaseModel):
    password: str = ""
```

After the existing endpoints (before the `app.mount("/", StaticFiles(...))` line), add:

```python
@app.get("/api/auth/status")
def auth_status(request: Request):
    cfg = _store.get_config_many(["auth_enabled", "cred_version"])
    enabled = not AUTH_DISABLED and cfg.get("auth_enabled") == "1"
    return {
        "auth_enabled": enabled,
        "authenticated": enabled and _token_ok(request, cfg),
    }


@app.post("/api/auth/login", dependencies=[Depends(block_cross_site)])
async def auth_login(body: LoginBody, request: Request, response: Response):
    ip = _client_ip(request)
    wait = _login_throttle.retry_after(ip)
    if wait > 0:
        return JSONResponse(
            {"detail": "too many attempts", "retry_after": wait},
            status_code=429, headers={"Retry-After": str(wait)},
        )
    if LOGIN_DELAY_SECONDS:
        await asyncio.sleep(LOGIN_DELAY_SECONDS)
    cfg = _store.get_config_many(["auth_enabled", "password"])
    if cfg.get("auth_enabled") != "1":
        raise HTTPException(status_code=400, detail="authentication is disabled")
    if not auth.verify_password(body.password, cfg.get("password") or ""):
        _login_throttle.record_failure(ip)
        raise HTTPException(status_code=401, detail="wrong password")
    _login_throttle.record_success(ip)
    _set_session_cookie(response, request)
    return {"ok": True}


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest service/tests/test_api.py::TestAuthEndpoints -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/main.py service/tests/test_api.py
git commit -m "feat: /api/auth status, login and logout endpoints"
```

---

## Task 6: `PUT /api/settings/auth`

**Files:**
- Modify: `service/main.py` (add `AuthSettingsBody` model + endpoint)
- Test: `service/tests/test_api.py`

**Interfaces:**
- Consumes: Task 4-5 helpers, `auth.hash_password`, `auth.verify_password`.
- Produces:
  - `PUT /api/settings/auth` (`{"enabled": bool, "new_password": str | None, "current_password": str | None}`) → `200 {"auth_enabled": bool}` (+ `Set-Cookie` when a login/re-issue happened); `403` wrong `current_password`; `422` password too short / missing when required.

- [ ] **Step 1: Write the failing tests**

Append to `service/tests/test_api.py`:

```python
class TestAuthSettings:
    def test_enable_requires_a_password(self, client):
        r = client.put("/api/settings/auth", json={"enabled": True})
        assert r.status_code == 422

    def test_enable_rejects_a_short_password(self, client):
        r = client.put("/api/settings/auth", json={"enabled": True, "new_password": "short"})
        assert r.status_code == 422

    def test_enable_sets_the_cookie_and_persists(self, client):
        r = client.put("/api/settings/auth", json={"enabled": True, "new_password": "secret123"})
        assert r.status_code == 200 and r.json() == {"auth_enabled": True}
        assert client.get("/api/locations").status_code == 200   # cookie from the PUT

    def test_change_password_needs_current_and_rotates_sessions(self, client):
        _enable_auth(client, "secret123")
        old = dict(client.cookies)
        bad = client.put("/api/settings/auth", json={
            "enabled": True, "current_password": "WRONG", "new_password": "newpass123"})
        assert bad.status_code == 403
        good = client.put("/api/settings/auth", json={
            "enabled": True, "current_password": "secret123", "new_password": "newpass123"})
        assert good.status_code == 200
        assert client.get("/api/locations").status_code == 200   # re-issued cookie
        client.cookies.clear()
        client.cookies.update(old)
        assert client.get("/api/locations").status_code == 401   # old session invalid

    def test_disable_needs_current_password(self, client):
        _enable_auth(client, "secret123")
        assert client.put("/api/settings/auth", json={
            "enabled": False, "current_password": "WRONG"}).status_code == 403
        assert client.put("/api/settings/auth", json={
            "enabled": False, "current_password": "secret123"}).status_code == 200
        client.cookies.clear()
        assert client.get("/api/locations").status_code == 200

    def test_reenable_with_stored_hash_needs_no_new_password(self, client):
        _enable_auth(client, "secret123")
        client.put("/api/settings/auth", json={"enabled": False, "current_password": "secret123"})
        r = client.put("/api/settings/auth", json={"enabled": True})
        assert r.status_code == 200 and r.json() == {"auth_enabled": True}
        client.cookies.clear()
        assert _login(client, "secret123").status_code == 200

    def test_blocks_cross_site(self, client):
        r = client.put("/api/settings/auth",
                       json={"enabled": True, "new_password": "secret123"},
                       headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest service/tests/test_api.py::TestAuthSettings -q`
Expected: FAIL — 404 / method not allowed

- [ ] **Step 3: Add the model and endpoint**

Near `class LoginBody` in `service/main.py`:

```python
class AuthSettingsBody(BaseModel):
    enabled: bool
    new_password: str | None = None
    current_password: str | None = None
```

After the `/api/auth/logout` endpoint:

```python
@app.put("/api/settings/auth", dependencies=[Depends(block_cross_site)])
def update_auth_settings(body: AuthSettingsBody, request: Request, response: Response):
    cfg = _store.get_config_many(["auth_enabled", "password", "cred_version"])
    currently_on = cfg.get("auth_enabled") == "1"
    stored = cfg.get("password") or ""
    version = int(cfg.get("cred_version") or "1")

    def require_current():
        if not auth.verify_password(body.current_password or "", stored):
            raise HTTPException(status_code=403, detail="current password is incorrect")

    def require_valid_new():
        if body.new_password is None or len(body.new_password) < PASSWORD_MIN_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"password must be at least {PASSWORD_MIN_LENGTH} characters",
            )

    if body.enabled:
        if currently_on:
            if body.new_password is not None:          # password change
                require_current()
                require_valid_new()
                _store.set_config("password", auth.hash_password(body.new_password))
                _store.set_config("cred_version", str(version + 1))
                _set_session_cookie(response, request)
            # enabled -> enabled with nothing to change: no-op
        else:                                          # enable
            if body.new_password is not None:
                require_valid_new()
                _store.set_config("password", auth.hash_password(body.new_password))
            elif not stored:
                raise HTTPException(status_code=422, detail="a password is required")
            _store.set_config("auth_enabled", "1")
            _store.set_config("cred_version", str(version + 1))
            _set_session_cookie(response, request)
    else:
        if currently_on:                               # disable
            require_current()
            _store.set_config("auth_enabled", "0")
        # already off: no-op

    return {"auth_enabled": _store.get_config("auth_enabled", "0") == "1"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest service/tests/test_api.py -q`
Expected: PASS — the full API suite, including the three `TestAuthGate` tests that were pending since Task 4.

- [ ] **Step 5: Run the whole backend suite**

Run: `python -m pytest -q`
Expected: PASS (all files)

- [ ] **Step 6: Commit**

```bash
git add service/main.py service/tests/test_api.py
git commit -m "feat: PUT /api/settings/auth to toggle auth and change the password"
```

---

## Task 7: `web/login.html`

**Files:**
- Create: `web/login.html`
- Test: `service/tests/test_api.py` (page-served assertion)

**Interfaces:**
- Consumes: `GET /api/auth/status`, `POST /api/auth/login`, `window.FindMyMap.t` (from `app.js`).
- Produces: a page served at `/login.html`.

- [ ] **Step 1: Write the failing test**

Append to `service/tests/test_api.py` (`TestAuthGate` class or a new `TestStaticPages`):

```python
class TestStaticPages:
    def test_login_page_is_served(self, client):
        assert client.get("/login.html").status_code == 200
```

(The test fixture writes a stub `login.html`; this only proves routing. Real markup is verified manually in Step 5.)

- [ ] **Step 2: Run test to verify it passes trivially now, then continue**

Run: `python -m pytest service/tests/test_api.py::TestStaticPages -q`
Expected: PASS (stub file). Keep going — the deliverable is the real page.

- [ ] **Step 3: Create `web/login.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title data-i18n="page_title_login">FindMy Map – Sign in</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="app.css" />
<script src="app.js"></script>
</head>
<body>
<main class="auth-page">
  <form id="login-form" class="auth-card">
    <h1 data-i18n="login_heading">FindMy Map</h1>
    <div class="field">
      <label for="password" data-i18n="f_password">Password</label>
      <input type="password" id="password" autocomplete="current-password" autofocus>
    </div>
    <div id="login-error" class="error-row" hidden></div>
    <button type="submit" class="btn btn-primary" data-i18n="sign_in">Sign in</button>
  </form>
</main>
<script>
(function () {
  const t = (k, v) => window.FindMyMap.t(k, v);
  const form = document.getElementById('login-form');
  const pw = document.getElementById('password');
  const err = document.getElementById('login-error');
  const btn = form.querySelector('button');

  function safeNext() {
    const raw = new URLSearchParams(location.search).get('next');
    if (!raw) return '/';
    try {
      // Resolve against our own origin; anything that lands elsewhere
      // (//evil, /\evil, https://evil, javascript:) is rejected.
      const u = new URL(raw, location.origin);
      if (u.origin === location.origin) return u.pathname + u.search + u.hash;
    } catch (e) {}
    return '/';
  }
  function showError(msg) { err.textContent = msg; err.hidden = false; }

  (async () => {
    try {
      const s = await (await fetch('/api/auth/status')).json();
      if (!s.auth_enabled || s.authenticated) location.replace(safeNext());
    } catch (e) {}
  })();

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.hidden = true;
    btn.disabled = true;
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw.value }),
      });
      if (res.ok) { location.replace(safeNext()); return; }
      if (res.status === 429) {
        const secs = (await res.json()).retry_after || 30;
        showError(t('login_throttled', { n: secs }));
        setTimeout(() => { btn.disabled = false; }, secs * 1000);
        return;
      }
      showError(t('login_wrong'));
    } catch (e) {
      showError(t('login_error'));
    }
    btn.disabled = false;
  });
})();
</script>
</body>
</html>
```

- [ ] **Step 4: Add the translation strings**

In `web/app.js`, in `STRINGS.en` add (near the other keys):

```javascript
      // login page
      page_title_login: 'FindMy Map – Sign in',
      login_heading: 'FindMy Map',
      f_password: 'Password',
      sign_in: 'Sign in',
      login_wrong: 'Wrong password.',
      login_throttled: 'Too many attempts — try again in {n} s.',
      login_error: 'Something went wrong. Try again.',
```

In `STRINGS.de`:

```javascript
      page_title_login: 'FindMy Map – Anmelden',
      login_heading: 'FindMy Map',
      f_password: 'Passwort',
      sign_in: 'Anmelden',
      login_wrong: 'Falsches Passwort.',
      login_throttled: 'Zu viele Versuche — in {n} s erneut probieren.',
      login_error: 'Etwas ist schiefgelaufen. Bitte erneut versuchen.',
```

- [ ] **Step 5: Manual smoke test**

```bash
# from the repo root, with a throwaway DB and the real web dir
GFM_HISTORY_DB=/tmp/fmm-smoke.db GFM_WEB_DIR=web GFM_NOMINATIM_URL= \
GFM_VENDOR_DIR=/does/not/matter GFM_LOGIN_DELAY_MS=0 \
python - <<'PY'
import sys, types
sys.modules['locations'] = types.SimpleNamespace(poll_all_devices=lambda: [])
sys.path.insert(0, 'service')
import uvicorn, main
uvicorn.run(main.app, host='127.0.0.1', port=8799)
PY
```
Open `http://127.0.0.1:8799/login.html` — with auth still off it should immediately redirect to `/`. Then in another shell:
`curl -X PUT localhost:8799/api/settings/auth -H 'content-type: application/json' -d '{"enabled":true,"new_password":"secret123"}'`
Reload `/` → redirected to `/login.html`; wrong password shows the error; `secret123` logs in and lands on the map. `rm /tmp/fmm-smoke.db` after.

- [ ] **Step 6: Run the backend suite**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add web/login.html web/app.js service/tests/test_api.py
git commit -m "feat: login page"
```

---

## Task 8: `web/settings.html`

**Files:**
- Create: `web/settings.html`
- Modify: `web/app.js` (settings strings)
- Test: `service/tests/test_api.py` (page-served assertion)

**Interfaces:**
- Consumes: `GET /api/auth/status`, `PUT /api/settings/auth`, `POST /api/auth/logout`, `window.FindMyMap.{t, getLang, setLang, getTheme, setTheme, onLangChange}` (the last four from Task 9 — implemented next; the page still loads and the auth section works without them, the segmented controls light up once Task 9 lands).
- Produces: a page served at `/settings.html`.

- [ ] **Step 1: Write the failing test**

Append to `TestStaticPages` in `service/tests/test_api.py`:

```python
    def test_settings_page_is_served(self, client):
        assert client.get("/settings.html").status_code == 200

    def test_settings_page_requires_auth_when_enabled(self, client):
        _enable_auth(client)
        client.cookies.clear()
        r = client.get("/settings.html", follow_redirects=False)
        assert r.status_code == 302 and "/login.html" in r.headers["location"]
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest service/tests/test_api.py::TestStaticPages -q`
Expected: `test_settings_page_is_served` passes on the stub; `test_settings_page_requires_auth_when_enabled` passes (middleware already gates non-public paths). If both pass, continue to the real page.

- [ ] **Step 3: Create `web/settings.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title data-i18n="page_title_settings">FindMy Map – Settings</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="app.css" />
<script src="app.js"></script>
</head>
<body>
<main class="auth-page">
  <div class="auth-card settings-card">
    <div class="settings-head">
      <h1 data-i18n="settings_heading">Settings</h1>
      <a class="btn" href="index.html" data-i18n="back_to_map">← Back to map</a>
    </div>

    <section class="settings-section">
      <h2 data-i18n="s_language">Language</h2>
      <div class="seg" id="lang-seg">
        <button type="button" data-value="en">EN</button>
        <button type="button" data-value="de">DE</button>
      </div>
    </section>

    <section class="settings-section">
      <h2 data-i18n="s_theme">Theme</h2>
      <div class="seg" id="theme-seg">
        <button type="button" data-value="light" data-i18n="theme_light">Light</button>
        <button type="button" data-value="dark" data-i18n="theme_dark">Dark</button>
      </div>
    </section>

    <section class="settings-section">
      <h2 data-i18n="s_auth">Authentication</h2>
      <label class="check-row">
        <input type="checkbox" id="auth-enabled">
        <span data-i18n="require_login">Require login</span>
      </label>

      <div id="auth-fields" hidden>
        <div class="field" id="cur-field" hidden>
          <label for="cur-pw" data-i18n="f_current_password">Current password</label>
          <input type="password" id="cur-pw" autocomplete="current-password">
        </div>
        <div class="field">
          <label for="new-pw" id="new-pw-label" data-i18n="f_new_password">New password</label>
          <input type="password" id="new-pw" autocomplete="new-password">
        </div>
        <div class="field">
          <label for="confirm-pw" data-i18n="f_confirm_password">Confirm password</label>
          <input type="password" id="confirm-pw" autocomplete="new-password">
        </div>
      </div>

      <div id="auth-msg" hidden></div>
      <button type="button" id="auth-save" class="btn btn-primary" data-i18n="save">Save</button>
      <button type="button" id="logout-btn" class="btn" data-i18n="log_out" hidden>Log out</button>
    </section>
  </div>
</main>
<script>
(function () {
  const FMM = window.FindMyMap;
  const t = (k, v) => FMM.t(k, v);

  function wireSeg(id, get, set) {
    const seg = document.getElementById(id);
    function render() {
      const cur = get ? get() : null;
      seg.querySelectorAll('button').forEach(b =>
        b.classList.toggle('active', b.dataset.value === cur));
    }
    seg.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (b && set) { set(b.dataset.value); render(); }
    });
    render();
    return render;
  }
  const renderLang = wireSeg('lang-seg', FMM.getLang, FMM.setLang);
  wireSeg('theme-seg', FMM.getTheme, FMM.setTheme);

  const box = document.getElementById('auth-enabled');
  const fields = document.getElementById('auth-fields');
  const curField = document.getElementById('cur-field');
  const newLabel = document.getElementById('new-pw-label');
  const msg = document.getElementById('auth-msg');
  const saveBtn = document.getElementById('auth-save');
  const logoutBtn = document.getElementById('logout-btn');
  const curPw = document.getElementById('cur-pw');
  const newPw = document.getElementById('new-pw');
  const confirmPw = document.getElementById('confirm-pw');
  let state = { auth_enabled: false };

  function renderAuth() {
    const on = state.auth_enabled;
    fields.hidden = !box.checked;
    curField.hidden = !on;
    newLabel.textContent = on ? t('f_new_password_optional') : t('f_new_password');
    logoutBtn.hidden = !on;
  }
  box.addEventListener('change', renderAuth);

  function setMsg(text, isError) {
    msg.textContent = text || '';
    msg.className = isError ? 'error-row' : 'muted';
    msg.hidden = !text;
  }

  async function load() {
    try { state = await (await fetch('/api/auth/status')).json(); }
    catch (e) { state = { auth_enabled: false }; }
    box.checked = state.auth_enabled;
    renderAuth();
  }

  saveBtn.addEventListener('click', async () => {
    setMsg('');
    const enabled = box.checked;
    const body = { enabled };
    if (enabled) {
      const np = newPw.value, cp = confirmPw.value;
      if (np || cp || !state.auth_enabled) {
        if (np.length < 8) { setMsg(t('err_pw_short'), true); return; }
        if (np !== cp) { setMsg(t('err_pw_mismatch'), true); return; }
        body.new_password = np;
      }
      if (state.auth_enabled) body.current_password = curPw.value;
    } else {
      body.current_password = curPw.value;
    }
    saveBtn.disabled = true;
    try {
      const res = await fetch('/api/settings/auth', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        curPw.value = newPw.value = confirmPw.value = '';
        await load();
        setMsg(state.auth_enabled ? t('auth_saved_on') : t('auth_saved_off'), false);
      } else if (res.status === 403) {
        setMsg(t('err_current_pw'), true);
      } else if (res.status === 422) {
        setMsg(t('err_pw_short'), true);
      } else {
        setMsg(t('login_error'), true);
      }
    } catch (e) {
      setMsg(t('login_error'), true);
    }
    saveBtn.disabled = false;
  });

  logoutBtn.addEventListener('click', async () => {
    try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (e) {}
    location.replace('/login.html');
  });

  FMM.onLangChange = () => { renderLang(); renderAuth(); };
  load();
})();
</script>
</body>
</html>
```

- [ ] **Step 4: Add the translation strings**

In `web/app.js` `STRINGS.en`:

```javascript
      // settings page
      settings: 'Settings',
      page_title_settings: 'FindMy Map – Settings',
      settings_heading: 'Settings',
      s_language: 'Language',
      s_theme: 'Theme',
      s_auth: 'Authentication',
      theme_light: 'Light',
      theme_dark: 'Dark',
      require_login: 'Require login',
      f_current_password: 'Current password',
      f_new_password: 'Password',
      f_new_password_optional: 'New password (leave blank to keep)',
      f_confirm_password: 'Confirm password',
      log_out: 'Log out',
      auth_saved_on: 'Saved. A login is now required.',
      auth_saved_off: 'Saved. Login is no longer required.',
      err_pw_short: 'Password must be at least 8 characters.',
      err_pw_mismatch: 'The passwords do not match.',
      err_current_pw: 'Current password is incorrect.',
```

In `STRINGS.de`:

```javascript
      settings: 'Einstellungen',
      page_title_settings: 'FindMy Map – Einstellungen',
      settings_heading: 'Einstellungen',
      s_language: 'Sprache',
      s_theme: 'Design',
      s_auth: 'Authentifizierung',
      theme_light: 'Hell',
      theme_dark: 'Dunkel',
      require_login: 'Login erforderlich',
      f_current_password: 'Aktuelles Passwort',
      f_new_password: 'Passwort',
      f_new_password_optional: 'Neues Passwort (leer lassen zum Behalten)',
      f_confirm_password: 'Passwort bestätigen',
      log_out: 'Abmelden',
      auth_saved_on: 'Gespeichert. Ein Login ist jetzt erforderlich.',
      auth_saved_off: 'Gespeichert. Kein Login mehr erforderlich.',
      err_pw_short: 'Das Passwort muss mindestens 8 Zeichen haben.',
      err_pw_mismatch: 'Die Passwörter stimmen nicht überein.',
      err_current_pw: 'Aktuelles Passwort ist falsch.',
```

- [ ] **Step 5: Run the backend suite**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/settings.html web/app.js service/tests/test_api.py
git commit -m "feat: settings page (language, theme, authentication)"
```

---

## Task 9: Header gear + `app.js` API + `app.css`

**Files:**
- Modify: `web/index.html` (lines 17-21), `web/timeline.html` (lines 17-21)
- Modify: `web/app.js` (STRINGS lines 9-12; `applyTheme` 169-179; `applyLangToggle` 182-188 + call at 195; public API 202-208; `setup` 212-230)
- Modify: `web/app.css` (drop line 80; add the standalone-page styles)
- Test: `service/tests/test_api.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `window.FindMyMap.setTheme(theme: "light"|"dark") -> void` (persists + fires `onThemeChange`)
  - `window.FindMyMap.getTheme() -> "light"|"dark"`
  - `window.FindMyMap.setLang(lang: "en"|"de") -> void`
  - `window.FindMyMap.getLang() -> "en"|"de"` (already exists)
  - `index.html` / `timeline.html` header contains `settings.html` and no `theme-toggle`/`lang-toggle`.

- [ ] **Step 1: Write the failing tests**

Append to `service/tests/test_api.py` as **module-level functions** (not inside `TestStaticPages` — they take no fixture). The `client` fixture writes a *stub* `index.html`, so these read the real files from the repo's `web/` dir:

```python
def test_real_index_header_has_gear_and_no_toggles():
    html = (pathlib.Path(__file__).parents[2] / "web" / "index.html").read_text()
    assert 'href="settings.html"' in html
    assert 'id="theme-toggle"' not in html
    assert 'id="lang-toggle"' not in html


def test_real_timeline_header_has_gear_and_no_toggles():
    html = (pathlib.Path(__file__).parents[2] / "web" / "timeline.html").read_text()
    assert 'href="settings.html"' in html
    assert 'id="theme-toggle"' not in html
    assert 'id="lang-toggle"' not in html
```

Add `import pathlib` at the top of `test_api.py` if not present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest service/tests/test_api.py -k "header_has_gear" -q`
Expected: FAIL — the toggles are still there.

- [ ] **Step 3: Edit `web/index.html`**

Replace lines 19-20:

```html
        <button id="lang-toggle" class="icon-btn" type="button" aria-label="Switch language">EN</button>
        <button id="theme-toggle" class="icon-btn" type="button" aria-label="Toggle theme">☀</button>
```

with:

```html
        <a id="settings-link" class="icon-btn" href="settings.html" data-i18n-aria="settings" aria-label="Settings">⚙</a>
```

- [ ] **Step 4: Edit `web/timeline.html`**

Make the exact same replacement of lines 19-20.

- [ ] **Step 5: Edit `web/app.js` — remove the dead toggle code**

1. In `STRINGS.en` and `STRINGS.de`, delete the three now-unused keys `toggle_theme_to_dark`, `toggle_theme_to_light`, `switch_language`. Keep `toggle_sheet`.
2. Replace `applyTheme` (lines 169-179) with:

```javascript
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('theme', theme); } catch (e) {}
  }
```

3. Delete the `applyLangToggle` function entirely (lines 182-188).
4. In `setLang`, delete the `applyLangToggle();` line (line 195).
5. In `setup()`, delete `applyLangToggle();` (line 214) and both the `themeBtn` block (217-224) and the `langBtn` block (226-229). `setup()` becomes:

```javascript
  function setup() {
    applyStaticI18n();
    applyTheme(currentTheme());
  }
```

6. In the public-API block (after `window.FindMyMap.onLangChange = null;`, line 208), add:

```javascript
  window.FindMyMap.setLang = setLang;
  window.FindMyMap.getTheme = currentTheme;
  window.FindMyMap.setTheme = function (theme) {
    applyTheme(theme === 'light' ? 'light' : 'dark');
    if (typeof window.FindMyMap.onThemeChange === 'function') {
      window.FindMyMap.onThemeChange(theme);
    }
  };
```

- [ ] **Step 6: Edit `web/app.css`**

Delete line 80 (`#lang-toggle { font-size: 11px; ... }`).

Append at the end of the file:

```css
/* --- Standalone pages: login + settings ------------------------------ */
.auth-page {
  min-height: 100%; display: flex; align-items: flex-start;
  justify-content: center; padding: 40px 16px;
}
.auth-card {
  width: 100%; max-width: 380px;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; padding: 24px;
}
.auth-card h1 { font-size: 18px; margin: 0 0 16px; }
.settings-card { max-width: 460px; }
.settings-head { display: flex; align-items: center; gap: 12px; }
.settings-head h1 { flex: 1; margin: 0; }
.settings-head .btn { width: auto; margin-top: 0; white-space: nowrap; }
.settings-section { margin-top: 22px; }
.settings-section h2 {
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted); margin: 0 0 8px;
}
.seg { display: flex; gap: 6px; }
.seg button {
  flex: 1; padding: 7px 10px; font-size: 13px; cursor: pointer;
  background: var(--panel-2); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
}
.seg button.active {
  background: var(--accent); border-color: var(--accent);
  color: #0b1220; font-weight: 600;
}
.check-row { display: flex; align-items: center; gap: 8px; font-size: 13px; }
#auth-msg:not([hidden]) { font-size: 12px; margin-top: 10px; }
```

- [ ] **Step 7: Run tests + manual check**

Run: `python -m pytest -q`
Expected: PASS

Manual: repeat the Task 7 Step 5 smoke server. Visit `/settings.html` — the EN/DE and Light/Dark segmented controls highlight the current value and switch instantly; the map page header shows only the gear; the gear opens settings.

- [ ] **Step 8: Commit**

```bash
git add web/index.html web/timeline.html web/app.js web/app.css service/tests/test_api.py
git commit -m "feat: header settings gear; move theme/language to the settings page"
```

---

## Task 10: Documentation and packaging

**Files:**
- Modify: `SECURITY.md`, `README.md`, `.env.example`, `docker-compose.yml`

**Interfaces:** none (docs only).

- [ ] **Step 1: Rewrite the top of `SECURITY.md`**

Replace the section `## The service has no authentication — put it behind an authenticating proxy` (down to the "Treat the database…" paragraph, which stays) with:

```markdown
## Authentication

`findmy-map` has an **optional** built-in login: a single account (the
form asks only for a password), a signed session cookie, and per-IP
throttling of failed attempts. It is **disabled by default**. Enable it
and set the password on the settings page (the gear icon in the header).

### With authentication enabled

You may expose the service directly — **but only over HTTPS**. Without
TLS the password and the session cookie travel in clear. When the request
is HTTPS the cookie is flagged `Secure` automatically (detected from the
request scheme / `X-Forwarded-Proto`).

A TLS-terminating reverse proxy is the usual way to add HTTPS. If it runs
on the same host, start uvicorn with `--proxy-headers
--forwarded-allow-ips=<proxy-ip>` so the login throttle sees real client
IPs (the `Secure` detection works regardless).

`GFM_LOGIN_DELAY_MS` (default `500`) is a fixed delay added to every login
attempt. After 5 failures from one IP within 15 minutes that IP is put on
a cooldown that grows 30 s → 2 min → 10 min → 30 min.

**Forgot the password / locked out:** set `GFM_AUTH_DISABLE=1` in the
environment and restart — authentication is then forced off regardless of
the stored setting, so you can open the settings page and set a new one.

### With authentication disabled

The service has **no access control of any kind** — anyone who can reach
the HTTP port sees the full location history. You **must** run it behind
an authenticating reverse proxy, a VPN, or Tailscale. The provided
`docker-compose.yml` publishes no ports and attaches only to an external
`proxy-net` network for this reason.
```

Keep the "Treat the database…" paragraph and the "Defence-in-depth" list;
in that list add two bullets:

```markdown
- **Password storage.** The password is stored as a stdlib `scrypt` hash
  (`n=2^14, r=8, p=1`), never in clear; verification is constant-time.
- **Session tokens.** The session cookie is an HMAC-SHA256-signed token
  bound to a `cred_version` counter; changing the password (or toggling
  auth on) increments it and invalidates every existing session.
```

- [ ] **Step 2: Add a `README.md` subsection**

Under `## Web UI`, after the `- **Timeline** …` bullet, add:

```markdown

### Authentication

Optional and **off by default**. Open the settings page (the ⚙ icon in the
header), tick **Require login** and set a password (min. 8 characters).
From then on every page and API call needs the session cookie from the
login page. The same settings page changes the password or turns auth off
again (both ask for the current password).

If you lock yourself out, set `GFM_AUTH_DISABLE=1` and restart — auth is
forced off so you can reset it. With auth enabled you can expose the
service directly, but **only over HTTPS** (see `SECURITY.md`).
```

In the `## Environment variables` table add a row:

```markdown
| `GFM_AUTH_DISABLE` | – | `1` forces the optional login off (recovery from a lost password) |
| `GFM_LOGIN_DELAY_MS` | `500` | fixed delay per login attempt |
```

- [ ] **Step 3: `.env.example`**

In the `# --- Optional tuning` block add:

```bash

# Optional built-in login (configured on the settings page, off by
# default). Set to 1 to force it OFF regardless of the stored setting --
# use this to recover from a lost password, then reset it on the
# settings page.
# GFM_AUTH_DISABLE=1

# Fixed delay (milliseconds) added to every login attempt.
# GFM_LOGIN_DELAY_MS=500
```

- [ ] **Step 4: `docker-compose.yml`**

Bump the image tag on the `findmy-map` service from `:0.1.1` to `:0.1.2`.

In the `findmy-map` service, after the `networks:` block and before
`environment:`, add a commented `ports:` example:

```yaml
    # findmy-map has an optional built-in login (see SECURITY.md). With it
    # enabled you can publish the port directly instead of going through
    # proxy-net -- but only behind HTTPS. Uncomment and adjust:
    # ports:
    #   - "127.0.0.1:8080:8080"
```

- [ ] **Step 5: Run the whole suite one more time**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add SECURITY.md README.md .env.example docker-compose.yml
git commit -m "docs: document optional authentication; bump compose image to 0.1.2"
```

---

## Post-plan (manual, not a task)

- Merge `v0.1.2-optional-auth` into `main`.
- Push a `v0.1.2` tag — the existing `.github/workflows/release.yml` builds and pushes `ghcr.io/exxt4zzy/google-findmy-map:0.1.2` and updates `:latest`.
- Fill in the GitHub release notes for `v0.1.2`.

---

## Self-Review

**1. Spec coverage**

| Spec section | Task(s) |
|---|---|
| `app_config` table + accessors + `session_secret` | Task 1 |
| `hash_password` / `verify_password` (scrypt, constant-time) | Task 2 |
| `make_session_token` / `parse_session_token` (HMAC, cred_version, max-age, skew) | Task 2 |
| `LoginThrottle` (per-IP, growing cooldown, window, clear-on-success) | Task 3 |
| Env knobs `GFM_AUTH_DISABLE`, `GFM_LOGIN_DELAY_MS` | Task 4 |
| Auth-gate middleware (allowlist, 401 vs 302, `?next=`) | Task 4 |
| `request_is_https` helper (X-Forwarded-Proto, first token) | Task 4 |
| Session-secret generated at startup | Task 4 (lifespan) |
| `GET /api/auth/status` (`authenticated` false when disabled) | Task 5 |
| `POST /api/auth/login` (throttle → delay → verify; 400/401/429; Secure-flag) | Task 5 |
| `POST /api/auth/logout` | Task 5 |
| `PUT /api/settings/auth` (bootstrap vs authed; enable/change/disable; cred_version bump on every enable and on password change; ≥ 8 chars; 403/422; re-issue cookie) | Task 6 |
| `web/login.html` (status redirect, `?next=` sanitising, 401/429 handling) | Task 7 |
| `web/settings.html` (language, theme, auth section states, logout) | Task 8 |
| Header gear replaces both toggles on both pages | Task 9 |
| `app.js`: keep sync head apply; drop button wiring; expose `setTheme/getTheme/setLang` | Task 9 |
| `app.css` standalone-page styles; drop `#lang-toggle` | Task 9 |
| `SECURITY.md` rewrite; `README.md`; `.env.example`; `docker-compose.yml` ports + tag | Task 10 |
| Tests: `test_auth.py`, `test_store.py` config, `test_api.py` gating/endpoints/settings/pages | Tasks 1-9 |
| Migration: table auto-created, default off, no image change needed | Task 1 (schema) + Task 10 (tag) |

No gaps.

**2. Placeholder scan** — every code step contains full code. The `test_api.py` `_build_client` refactor and the `pathlib` real-file reads are spelled out. No "TBD"/"add error handling"/"similar to Task N".

**3. Type consistency**

- `get_config_many` returns `dict[str, str]` with missing keys omitted — every caller (`_auth_gate`, `auth_status`, `auth_login`, `update_auth_settings`) uses `.get(...)` with a fallback. ✔
- `_token_ok(request, cfg)` signature identical in Task 4 definition and all Task 5/6 call sites; `cfg` always contains `cred_version` where it is called (`_auth_gate` fetches `["auth_enabled","cred_version"]`, `auth_status` the same). ✔
- `parse_session_token(token, secret, cred_version, *, max_age, now)` — Task 2 definition matches the Task 4 call `auth.parse_session_token(token, _store.session_secret(), int(cfg.get("cred_version") or "1"))`. ✔
- `make_session_token(secret, cred_version, *, now)` — matches the `_set_session_cookie` call. ✔
- `_set_session_cookie(response, request)` — Task 4 definition; Task 5/6 call sites pass exactly `(response, request)`. ✔
- Cookie name constant `SESSION_COOKIE = "fmm_session"` used in middleware, `_set_session_cookie`, `auth_logout`, and asserted literally as `"fmm_session"` in tests. ✔
- `window.FindMyMap.setTheme/getTheme/setLang/getLang` defined in Task 9, consumed in Task 8's `settings.html`. Task 8 note flags the ordering (settings page ships first, controls activate after Task 9) — acceptable because the auth section is independent and Task 9 immediately follows. ✔
- `PASSWORD_MIN_LENGTH = 8` in `main.py` (Task 4) reused in Task 6; the frontend hard-codes `8` and the `err_pw_short` string says "8" — consistent with the Global Constraints value. ✔
