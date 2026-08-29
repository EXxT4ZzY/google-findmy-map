"""End-to-end checks for the HTTP API, with the heavy vendored
``locations`` module stubbed out."""

import sys
import types

import pytest


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


def _enable_auth(client, password="secret123"):
    r = client.put("/api/settings/auth", json={"enabled": True, "new_password": password})
    assert r.status_code == 200
    return r


def _login(client, password):
    return client.post("/api/auth/login", json={"password": password})


def test_history_endpoint_returns_points_in_the_window(client):
    store = client._main._store
    for ts in (1_000, 2_000, 3_000, 4_000):
        store.add("dev-x", {"latitude": 52.5, "longitude": 13.4, "time": ts, "accuracy": 5})

    resp = client.get("/api/history", params={"device": "dev-x", "start": 2_000, "end": 3_000})

    assert resp.status_code == 200
    body = resp.json()
    assert body["device"] == "dev-x"
    assert [p["time"] for p in body["points"]] == [2_000, 3_000]


def test_history_endpoint_defaults_to_the_last_seven_days(client):
    import time

    store = client._main._store
    now = int(time.time())
    store.add("dev-x", {"latitude": 1, "longitude": 2, "time": now - 3_600, "accuracy": 5})
    store.add("dev-x", {"latitude": 1, "longitude": 2, "time": now - 30 * 24 * 3600, "accuracy": 5})

    body = client.get("/api/history", params={"device": "dev-x"}).json()

    assert [p["time"] for p in body["points"]] == [now - 3_600]


def test_history_endpoint_unknown_device_returns_empty(client):
    body = client.get("/api/history", params={"device": "nope"}).json()
    assert body["points"] == [] and body["name"] is None


def test_locations_endpoint_still_responds(client):
    resp = client.get("/api/locations")
    assert resp.status_code == 200
    assert "devices" in resp.json()


def test_locations_endpoint_exposes_the_palette(client):
    body = client.get("/api/locations").json()
    assert isinstance(body["palette"], list) and body["palette"]


def _seed_one_device(main, name="iPhone", id="dev-1"):
    with main._state_lock:
        main._state["devices"] = main._augment_all([{
            "name": name, "id": id, "type": "geo",
            "latitude": 52.5, "longitude": 13.4, "time": 1000, "accuracy": 5,
        }])


def _device(client, id="dev-1"):
    return next(d for d in client.get("/api/locations").json()["devices"] if d["id"] == id)


def test_update_device_sets_name_and_colour(client):
    _seed_one_device(client._main)

    resp = client.put("/api/devices/dev-1", json={"name": "Backpack", "color": "#123456"})
    assert resp.status_code == 200

    dev = _device(client)
    assert dev["name"] == "Backpack"
    assert dev["color"] == "#123456"
    assert dev["default_name"] == "iPhone"


def test_update_device_persists_to_the_store(client):
    client.put("/api/devices/dev-9", json={"name": "X", "color": "#abcdef"})
    assert client._main._store.get_settings()["dev-9"] == {"name": "X", "color": "#abcdef"}


def test_clearing_settings_restores_the_defaults(client):
    _seed_one_device(client._main)
    client.put("/api/devices/dev-1", json={"name": "Backpack", "color": "#123456"})
    client.put("/api/devices/dev-1", json={"name": "", "color": ""})

    dev = _device(client)
    assert dev["name"] == "iPhone"
    assert dev["color"] != "#123456"


def test_update_device_rejects_a_non_hex_colour(client):
    resp = client.put("/api/devices/dev-1", json={"name": "X", "color": "red"})
    assert resp.status_code == 422


def test_mutating_endpoints_reject_cross_site_requests(client):
    assert client.post("/api/refresh", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.put("/api/devices/d", json={"name": "x"},
                      headers={"sec-fetch-site": "same-site"}).status_code == 403


def test_mutating_endpoints_allow_same_origin_and_non_browser(client):
    assert client.post("/api/refresh", headers={"sec-fetch-site": "same-origin"}).status_code == 200
    assert client.post("/api/refresh").status_code == 200  # no header (curl/scripts)


def test_read_endpoints_are_not_blocked_cross_site(client):
    assert client.get("/api/locations", headers={"sec-fetch-site": "cross-site"}).status_code == 200


def _seed_stay(store, device="dev-1", lat=52.52, lon=13.405, start=1_000_000, count=16):
    for i in range(count):
        store.add(device, {"latitude": lat + (i % 3) * 1e-5, "longitude": lon,
                           "time": start + i * 120, "accuracy": 10})


def test_visits_endpoint_detects_a_stay(client):
    _seed_stay(client._main._store)
    body = client.get("/api/visits", params={"device": "dev-1",
                                             "start": 999_000, "end": 1_100_000}).json()
    assert body["geocoding"] is False
    assert len(body["visits"]) == 1
    v = body["visits"][0]
    assert v["start"] == 1_000_000 and v["end"] == 1_000_000 + 15 * 120
    assert v["label"] is None


def test_visits_endpoint_surfaces_cached_addresses(client):
    main = client._main
    _seed_stay(main._store)
    found = __import__("visits").detect_visits(
        main._store.range("dev-1", 0, 2_000_000), main.VISIT_RADIUS_M, main.VISIT_MIN_SECONDS
    )
    main._store.geocode_put(found[0]["lat"], found[0]["lon"], "Home", "Home, Berlin")

    body = client.get("/api/visits", params={"device": "dev-1",
                                             "start": 0, "end": 2_000_000}).json()
    assert body["visits"][0]["label"] == "Home"
    assert body["visits"][0]["address"] == "Home, Berlin"


def test_visits_endpoint_queues_uncached_coords_when_geocoding_is_on(client):
    from geocode import Geocoder

    main = client._main
    main._geocoder = Geocoder(main._store, base_url="https://example.test",
                              http_get=lambda url: {"display_name": "Place, City", "address": {}})
    _seed_stay(main._store)

    body = client.get("/api/visits", params={"device": "dev-1",
                                             "start": 0, "end": 2_000_000}).json()
    assert body["geocoding"] is True
    assert body["pending"] == 1
    assert main._geocoder.pending_count == 1

    main._geocoder._drain_one()
    body2 = client.get("/api/visits", params={"device": "dev-1",
                                              "start": 0, "end": 2_000_000}).json()
    assert body2["visits"][0]["label"] == "Place"
    assert body2["pending"] == 0


class TestAuthGate:
    def test_auth_is_off_by_default(self, client):
        assert client.get("/api/locations").status_code == 200
        assert client.get("/", follow_redirects=False).status_code == 200

    @pytest.mark.xfail(reason="/api/auth/* and /api/settings/auth land in Task 6", strict=False)
    def test_enabling_auth_gates_api_and_pages(self, client):
        _enable_auth(client)                       # PUT response sets the cookie
        assert client.get("/api/locations").status_code == 200
        client.cookies.clear()
        assert client.get("/api/locations").status_code == 401
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302 and "/login.html" in r.headers["location"]

    @pytest.mark.xfail(reason="/api/auth/* and /api/settings/auth land in Task 6", strict=False)
    def test_allowlisted_paths_reachable_while_locked(self, client):
        _enable_auth(client)
        client.cookies.clear()
        assert client.get("/login.html").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/api/auth/status").status_code == 200

    @pytest.mark.xfail(reason="/api/auth/* and /api/settings/auth land in Task 6", strict=False)
    def test_auth_disable_env_overrides_the_db(self, make_client):
        c1 = make_client()
        with c1:
            _enable_auth(c1)
        c2 = make_client(GFM_AUTH_DISABLE="1")
        with c2:
            c2.cookies.clear()
            assert c2.get("/api/locations").status_code == 200


_NEEDS_TASK6 = pytest.mark.xfail(
    reason="needs PUT /api/settings/auth from Task 6", strict=False
)


class TestAuthEndpoints:
    def test_status_reports_disabled(self, client):
        body = client.get("/api/auth/status").json()
        assert body == {"auth_enabled": False, "authenticated": False}

    @_NEEDS_TASK6
    def test_status_reports_enabled_and_authenticated(self, client):
        _enable_auth(client)
        body = client.get("/api/auth/status").json()
        assert body["auth_enabled"] is True and body["authenticated"] is True
        client.cookies.clear()
        body2 = client.get("/api/auth/status").json()
        assert body2["auth_enabled"] is True and body2["authenticated"] is False

    @_NEEDS_TASK6
    def test_login_wrong_then_right(self, client):
        _enable_auth(client, "hunter2222")
        client.cookies.clear()
        assert _login(client, "nope").status_code == 401
        r = _login(client, "hunter2222")
        assert r.status_code == 200
        assert client.get("/api/locations").status_code == 200

    def test_login_when_disabled_is_400(self, client):
        assert _login(client, "whatever").status_code == 400

    @_NEEDS_TASK6
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
        r = client.post("/api/auth/logout")
        assert r.status_code == 200
        set_cookie = r.headers.get("set-cookie", "").lower()
        assert "fmm_session=" in set_cookie
        assert 'max-age=0' in set_cookie or '01 jan 1970' in set_cookie

    @_NEEDS_TASK6
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
        r = client.post("/api/auth/login", json={"password": "secret123"},
                        headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403
