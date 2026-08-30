"""End-to-end checks for the HTTP API, with the heavy vendored
``locations`` module stubbed out."""

import pathlib
import sys
import time
import types

import pytest


def _build_client(tmp_path, monkeypatch, env=None):
    stub = types.ModuleType("locations")
    stub.poll_all_devices = lambda: []
    stub.start_sound = lambda device_id: True
    stub.stop_sound = lambda device_id: True
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
        ("favicon.svg", "<svg></svg>"),
        ("favicon.ico", "fake-ico"),
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


def _enable_auth(client, password="secret123", username="admin"):
    r = client.put("/api/settings/auth",
                   json={"enabled": True, "new_password": password, "username": username})
    assert r.status_code == 200
    return r


def _login(client, password, username="admin"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


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
    assert client.post("/api/devices/d/ring",
                       headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post("/api/devices/d/ring/stop",
                       headers={"sec-fetch-site": "cross-site"}).status_code == 403


def test_mutating_endpoints_allow_same_origin_and_non_browser(client):
    assert client.post("/api/refresh", headers={"sec-fetch-site": "same-origin"}).status_code == 200
    assert client.post("/api/refresh").status_code == 200  # no header (curl/scripts)


def test_ring_device_starts_and_stops(client):
    assert client.post("/api/devices/dev-1/ring").status_code == 200
    assert client.post("/api/devices/dev-1/ring/stop").status_code == 200


def test_ring_device_surfaces_a_failure(client):
    client._main.locations.start_sound = lambda device_id: False
    resp = client.post("/api/devices/dev-1/ring")
    assert resp.status_code == 502


def test_stop_ring_surfaces_a_failure(client):
    client._main.locations.stop_sound = lambda device_id: False
    resp = client.post("/api/devices/dev-1/ring/stop")
    assert resp.status_code == 502


def test_devices_endpoint_lists_a_device_no_longer_in_the_live_poll(client):
    main = client._main
    _seed_one_device(main, name="iPhone", id="dev-1")   # persists last_known_name
    with main._state_lock:
        main._state["devices"] = []   # simulate: dev-1 dropped out of the live poll

    devices = client.get("/api/devices").json()["devices"]
    assert [d["id"] for d in devices] == ["dev-1"]
    assert devices[0]["name"] == "iPhone"
    assert devices[0]["last_seen"] == 1000


def test_devices_endpoint_prefers_a_manual_rename(client):
    main = client._main
    _seed_one_device(main, name="iPhone", id="dev-1")
    client.put("/api/devices/dev-1", json={"name": "Backpack", "color": ""})

    devices = client.get("/api/devices").json()["devices"]
    assert devices[0]["name"] == "Backpack"


def test_devices_endpoint_sorts_most_recently_seen_first(client):
    main = client._main
    _seed_one_device(main, name="Old", id="dev-old")
    main._store.add("dev-old", {"latitude": 1, "longitude": 1, "time": 1_000})
    main._store.add("dev-new", {"latitude": 1, "longitude": 1, "time": 5_000})
    main._store.set_last_seen_name("dev-new", "New")

    devices = client.get("/api/devices").json()["devices"]
    assert [d["id"] for d in devices] == ["dev-new", "dev-old"]


def test_semantic_location_does_not_clobber_the_device_name(client):
    """Regression test for the locations.py bug this feature fixed: merging
    a semantic-only fix into the device entry must not overwrite its name."""
    with client._main._state_lock:
        client._main._state["devices"] = client._main._augment_all([{
            "name": "iPhone", "id": "dev-2", "type": "semantic",
            "place_name": "Home", "time": 1000,
        }])

    dev = _device(client, id="dev-2")
    assert dev["name"] == "iPhone"
    assert dev["place_name"] == "Home"


def test_history_retention_prunes_only_when_configured_and_due(make_client):
    c = make_client(GFM_HISTORY_RETENTION_DAYS="1")
    with c:
        main = c._main
        now = int(time.time())
        main._store.add("dev-1", {"latitude": 1, "longitude": 1, "time": now - 2 * 86400})
        main._store.add("dev-1", {"latitude": 1, "longitude": 1, "time": now - 3600})

        # The background poll loop (stubbed to return no devices) already
        # ran its own _maybe_prune_history() once by now and may have
        # consumed the daily gate -- reset it so this call is deterministically due.
        main._last_prune["at"] = 0.0
        main._maybe_prune_history()
        points = main._store.range("dev-1", 0, now + 1)
        assert len(points) == 1 and points[0]["time"] == now - 3600

        # A second call right away is not due yet -- add an old point and
        # confirm it survives until the next scheduled prune.
        main._store.add("dev-1", {"latitude": 1, "longitude": 1, "time": now - 5 * 86400})
        main._maybe_prune_history()
        assert len(main._store.range("dev-1", 0, now + 1)) == 2


def test_history_retention_disabled_by_default(client):
    main = client._main
    assert main.HISTORY_RETENTION_DAYS == 0
    now = int(time.time())
    main._store.add("dev-1", {"latitude": 1, "longitude": 1, "time": now - 3650 * 86400})
    main._maybe_prune_history()
    assert len(main._store.range("dev-1", 0, now + 1)) == 1


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


class TestStaticPages:
    def test_login_page_is_served(self, client):
        assert client.get("/login.html").status_code == 200

    def test_settings_page_is_served(self, client):
        assert client.get("/settings.html").status_code == 200

    def test_settings_page_requires_auth_when_enabled(self, client):
        _enable_auth(client)
        client.cookies.clear()
        r = client.get("/settings.html", follow_redirects=False)
        assert r.status_code == 302 and "/login.html" in r.headers["location"]


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
        # The login page itself references these; they must not redirect to
        # login.html while locked out, or the tab icon (and any browser's
        # automatic /favicon.ico probe) silently breaks behind the gate.
        assert client.get("/favicon.svg").status_code == 200
        assert client.get("/favicon.ico").status_code == 200

    def test_auth_disable_allows_resetting_a_forgotten_password(self, make_client):
        """The documented recovery flow (README / SECURITY.md), end to end."""
        c1 = make_client()
        with c1:
            _enable_auth(c1, "orig-pass-1")

        c2 = make_client(GFM_AUTH_DISABLE="1")
        with c2:
            c2.cookies.clear()
            assert c2.get("/api/auth/status").json() == {
                "auth_enabled": False, "authenticated": False}
            # No current_password: it is the one the operator forgot.
            r = c2.put("/api/settings/auth",
                       json={"enabled": True, "new_password": "brandnew-1"})
            assert r.status_code == 200

        c3 = make_client(GFM_AUTH_DISABLE="")   # escape hatch removed again
        with c3:
            c3.cookies.clear()
            assert _login(c3, "brandnew-1").status_code == 200
            c3.cookies.clear()
            assert _login(c3, "orig-pass-1").status_code == 401

    def test_auth_disable_env_overrides_the_db(self, make_client):
        c1 = make_client()
        with c1:
            _enable_auth(c1)
        c2 = make_client(GFM_AUTH_DISABLE="1")
        with c2:
            c2.cookies.clear()
            assert c2.get("/api/locations").status_code == 200


class TestAuthEndpoints:
    def test_status_reports_disabled(self, client):
        body = client.get("/api/auth/status").json()
        assert body == {"auth_enabled": False, "authenticated": False}

    def test_status_reports_enabled_and_authenticated(self, client):
        _enable_auth(client)
        body = client.get("/api/auth/status").json()
        assert body["auth_enabled"] is True and body["authenticated"] is True
        # The username is only ever revealed to a caller who already holds a
        # valid session -- never to the anonymous request below.
        assert body["username"] == "admin"
        client.cookies.clear()
        body2 = client.get("/api/auth/status").json()
        assert body2["auth_enabled"] is True and body2["authenticated"] is False
        assert "username" not in body2

    def test_login_wrong_then_right(self, client):
        _enable_auth(client, "hunter2222")
        client.cookies.clear()
        assert _login(client, "nope").status_code == 401
        r = _login(client, "hunter2222")
        assert r.status_code == 200
        assert client.get("/api/locations").status_code == 200

    def test_login_wrong_username_is_rejected(self, client):
        _enable_auth(client, "hunter2222", username="admin")
        client.cookies.clear()
        assert _login(client, "hunter2222", username="someone-else").status_code == 401
        assert _login(client, "hunter2222", username="admin").status_code == 200

    def test_login_without_stored_username_accepts_any_username(self, client):
        """Backward compat: an install that enabled auth before this
        credential existed has a password but no stored username. Login
        must keep working there regardless of what (or whether) a username
        is submitted, so the upgrade never locks the operator out."""
        _enable_auth(client, "hunter2222", username="admin")
        store = client._main._store
        store.set_config("username", "")   # simulate a pre-upgrade install
        client.cookies.clear()
        assert _login(client, "hunter2222", username="").status_code == 200
        client.cookies.clear()
        assert _login(client, "hunter2222", username="whatever").status_code == 200

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
        r2 = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"},
                         headers={"x-forwarded-proto": "https"})
        assert "secure" in r2.headers["set-cookie"].lower()

    def test_login_blocks_cross_site(self, client):
        r = client.post("/api/auth/login", json={"password": "secret123"},
                        headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403


class TestAuthSettings:
    def test_enable_requires_a_password(self, client):
        r = client.put("/api/settings/auth", json={"enabled": True})
        assert r.status_code == 422

    def test_enable_rejects_a_short_password(self, client):
        r = client.put("/api/settings/auth", json={"enabled": True, "new_password": "short"})
        assert r.status_code == 422

    def test_enable_requires_a_username(self, client):
        r = client.put("/api/settings/auth",
                       json={"enabled": True, "new_password": "secret123"})
        assert r.status_code == 422

    def test_enable_rejects_a_blank_username(self, client):
        r = client.put("/api/settings/auth",
                       json={"enabled": True, "new_password": "secret123", "username": "   "})
        assert r.status_code == 422

    def test_enable_sets_the_cookie_and_persists(self, client):
        r = client.put("/api/settings/auth",
                       json={"enabled": True, "new_password": "secret123", "username": "admin"})
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

    def test_change_username_needs_current_and_rotates_sessions(self, client):
        _enable_auth(client, "secret123", username="admin")
        old = dict(client.cookies)
        bad = client.put("/api/settings/auth", json={
            "enabled": True, "current_password": "WRONG", "username": "new-admin"})
        assert bad.status_code == 403
        good = client.put("/api/settings/auth", json={
            "enabled": True, "current_password": "secret123", "username": "new-admin"})
        assert good.status_code == 200
        assert client.get("/api/locations").status_code == 200   # re-issued cookie
        client.cookies.clear()
        client.cookies.update(old)
        assert client.get("/api/locations").status_code == 401   # old session invalid
        client.cookies.clear()
        assert _login(client, "secret123", username="admin").status_code == 401
        assert _login(client, "secret123", username="new-admin").status_code == 200

    def test_resending_the_same_username_is_a_noop(self, client):
        _enable_auth(client, "secret123", username="admin")
        store = client._main._store
        version = store.get_config("cred_version")
        r = client.put("/api/settings/auth", json={"enabled": True, "username": "admin"})
        assert r.status_code == 200
        assert store.get_config("cred_version") == version
        assert "set-cookie" not in {k.lower() for k in r.headers}

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

    def test_resaving_enabled_without_a_new_password_changes_nothing(self, client):
        _enable_auth(client, "secret123")
        store = client._main._store
        version = store.get_config("cred_version")
        old = dict(client.cookies)

        r = client.put("/api/settings/auth", json={"enabled": True})
        assert r.status_code == 200 and r.json() == {"auth_enabled": True}
        assert "set-cookie" not in {k.lower() for k in r.headers}
        assert store.get_config("cred_version") == version

        client.cookies.clear()
        client.cookies.update(old)
        assert client.get("/api/locations").status_code == 200   # session survived

    def test_saving_disabled_while_already_off_is_a_noop(self, client):
        store = client._main._store
        before = store.get_config_many(["auth_enabled", "password", "cred_version"])
        r = client.put("/api/settings/auth", json={"enabled": False})
        assert r.status_code == 200 and r.json() == {"auth_enabled": False}
        assert "set-cookie" not in {k.lower() for k in r.headers}
        assert store.get_config_many(["auth_enabled", "password", "cred_version"]) == before
        assert client.get("/api/locations").status_code == 200

    def test_blocks_cross_site(self, client):
        r = client.put("/api/settings/auth",
                       json={"enabled": True, "new_password": "secret123"},
                       headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403


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


def test_real_favicon_files_exist_and_are_referenced():
    web_dir = pathlib.Path(__file__).parents[2] / "web"
    svg = (web_dir / "favicon.svg").read_text()
    assert "<svg" in svg
    ico = (web_dir / "favicon.ico").read_bytes()
    assert ico[:4] == b"\x00\x00\x01\x00"   # ICO magic
    for page in ("index.html", "timeline.html", "login.html", "settings.html"):
        html = (web_dir / page).read_text()
        assert 'href="favicon.svg"' in html
        assert 'href="favicon.ico"' in html


def test_real_index_has_a_ring_button_wired_to_the_api():
    html = (pathlib.Path(__file__).parents[2] / "web" / "index.html").read_text()
    assert 'device-ring-btn' in html
    assert '/ring' in html


def test_real_ring_button_gives_instant_no_popup_feedback():
    """The pending/failed states must be set synchronously on click -- i.e.
    before the fetch is awaited -- and use no alert()/confirm()/toast."""
    html = (pathlib.Path(__file__).parents[2] / "web" / "index.html").read_text()
    assert "classList.add('pending')" in html
    assert "alert(" not in html and "confirm(" not in html
    css = (pathlib.Path(__file__).parents[2] / "web" / "app.css").read_text()
    assert ".device-ring-btn.pending" in css
    assert ".device-ring-btn.ring-failed" in css


def test_real_timeline_lists_devices_from_the_devices_endpoint():
    html = (pathlib.Path(__file__).parents[2] / "web" / "timeline.html").read_text()
    assert "fetch('/api/devices')" in html
