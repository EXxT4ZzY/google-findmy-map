import asyncio
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

# The vendored GoogleFindMyTools checkout must be on sys.path *before* we
# import anything from locations.py, since that module imports top-level
# packages (Auth, NovaApi, ProtoDecoders, ...) that only exist there.
VENDOR_DIR = Path(os.environ.get("GFM_VENDOR_DIR", "/app/vendor"))
sys.path.insert(0, str(VENDOR_DIR))

import re

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import colors
import locations
import visits as visits_mod
from augment import augment_device
from geocode import Geocoder
from store import LocationStore

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("findmy-map")

POLL_INTERVAL_SECONDS = int(os.environ.get("GFM_POLL_INTERVAL_SECONDS", "120"))
WEB_DIR = Path(os.environ.get("GFM_WEB_DIR", "/app/web"))
HISTORY_DB = Path(os.environ.get("GFM_HISTORY_DB", "/data/history.db"))
LEGACY_HISTORY_JSON = Path(os.environ.get("GFM_HISTORY_FILE", "/data/history.json"))
DEVICE_COLOR_OVERRIDES = colors.parse_overrides(os.environ.get("GFM_DEVICE_COLORS"))

NOMINATIM_URL = os.environ.get("GFM_NOMINATIM_URL", "https://nominatim.openstreetmap.org")
GEOCODE_EMAIL = os.environ.get("GFM_GEOCODE_EMAIL") or None
VISIT_RADIUS_M = float(os.environ.get("GFM_VISIT_RADIUS_M", "100"))
VISIT_MIN_SECONDS = int(float(os.environ.get("GFM_VISIT_MIN_MINUTES", "15")) * 60)

AUTH_DISABLED = os.environ.get("GFM_AUTH_DISABLE", "").strip().lower() in ("1", "true", "yes")
LOGIN_DELAY_SECONDS = int(os.environ.get("GFM_LOGIN_DELAY_MS", "500")) / 1000

DEFAULT_HISTORY_WINDOW_SECONDS = 7 * 24 * 3600

_state_lock = threading.Lock()
_state = {"devices": [], "last_poll": None, "last_error": None}
_store = LocationStore(HISTORY_DB)
_store.migrate_json(LEGACY_HISTORY_JSON)
_settings = _store.get_settings()  # {device_id: {"name", "color"}} from the web UI
_geocoder = Geocoder(_store, base_url=NOMINATIM_URL, email=GEOCODE_EMAIL)
_refresh_now = threading.Event()


def _augment_all(devices):
    """Attach history/name/colour to every device (also used after an edit)."""
    # Stable ordering -> each device without an explicit colour gets a
    # different palette colour (by position, not by hash).
    color_order = sorted(d["id"] for d in devices)
    return [
        augment_device(
            d, _store, DEVICE_COLOR_OVERRIDES, color_order.index(d["id"]), _settings
        )
        for d in devices
    ]


def _poll_loop():
    while True:
        try:
            devices = locations.poll_all_devices()
            with _state_lock:
                _state["devices"] = _augment_all(devices)
                _state["last_poll"] = int(time.time())
                _state["last_error"] = None
            log.info("Polled %d device(s).", len(devices))
        except Exception as exc:
            log.exception("Polling cycle failed")
            with _state_lock:
                _state["last_error"] = str(exc)

        _refresh_now.wait(POLL_INTERVAL_SECONDS)
        _refresh_now.clear()


@asynccontextmanager
async def lifespan(_app):
    _store.session_secret()  # ensure it exists before any request
    if AUTH_DISABLED:
        log.warning("GFM_AUTH_DISABLE is set -- built-in authentication is OFF.")
    threading.Thread(target=_poll_loop, daemon=True).start()
    _geocoder.start()
    yield
    _geocoder.stop()


app = FastAPI(lifespan=lifespan)


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


def block_cross_site(request: Request):
    """Reject state-changing requests made from another site.

    Defence in depth only -- this service has no authentication, so it MUST
    also sit behind an authenticating reverse proxy (see SECURITY.md). This
    uses the Fetch Metadata `Sec-Fetch-Site` header, which browsers set
    automatically and a cross-site page cannot forge; non-browser clients
    (curl, scripts) don't send it and are unaffected.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail="cross-site request rejected")


def _device_name(device_id):
    with _state_lock:
        for d in _state["devices"]:
            if d["id"] == device_id:
                return d.get("name")
    return None


@app.get("/api/locations")
def get_locations():
    with _state_lock:
        payload = dict(_state)
    payload["palette"] = colors.PALETTE
    return JSONResponse(payload)


@app.post("/api/refresh", dependencies=[Depends(block_cross_site)])
def trigger_refresh():
    _refresh_now.set()
    return {"status": "refresh_triggered"}


class DeviceSettingsBody(BaseModel):
    name: str | None = None
    color: str | None = None


class LoginBody(BaseModel):
    password: str = ""


@app.put("/api/devices/{device_id}", dependencies=[Depends(block_cross_site)])
def update_device(device_id: str, body: DeviceSettingsBody):
    """Set (or clear, with empty values) a device's display name and pin colour."""
    name = (body.name or "").strip()
    color = (body.color or "").strip()
    if color and not _HEX_COLOR.match(color):
        raise HTTPException(status_code=422, detail="color must be #rrggbb or empty")

    _store.set_setting(device_id, name=name, color=color)

    global _settings
    _settings = _store.get_settings()
    with _state_lock:
        _state["devices"] = _augment_all(_state["devices"])

    return {
        "status": "ok",
        "settings": _settings.get(device_id, {"name": None, "color": None}),
    }


@app.get("/api/history")
def get_history(device: str, start: int | None = None, end: int | None = None):
    """Full location track for one device within [start, end] (unix seconds)."""
    now = int(time.time())
    end = now if end is None else int(end)
    start = end - DEFAULT_HISTORY_WINDOW_SECONDS if start is None else int(start)

    return {
        "device": device,
        "name": _device_name(device),
        "start": start,
        "end": end,
        "points": _store.range(device, start, end),
    }


@app.get("/api/visits")
def get_visits(device: str, start: int | None = None, end: int | None = None):
    """Places the device stayed at within [start, end], newest-relevant first.

    Each visit carries a reverse-geocoded ``label``/``address`` when known;
    otherwise those are null and a background lookup is queued -- poll this
    endpoint again shortly to pick the addresses up.
    """
    now = int(time.time())
    end = now if end is None else int(end)
    start = end - DEFAULT_HISTORY_WINDOW_SECONDS if start is None else int(start)

    points = _store.range(device, start, end)
    found = visits_mod.detect_visits(points, VISIT_RADIUS_M, VISIT_MIN_SECONDS)

    out = []
    pending = 0
    for v in found:
        cached = _geocoder.lookup(v["lat"], v["lon"])
        label = cached["label"] if cached else None
        address = cached["address"] if cached else None
        if label is None and _geocoder.enqueue(v["lat"], v["lon"]):
            pending += 1
        out.append({**v, "label": label, "address": address})

    return {
        "device": device,
        "name": _device_name(device),
        "start": start,
        "end": end,
        "geocoding": _geocoder.enabled,
        "pending": pending,
        "visits": out,
    }


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


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
