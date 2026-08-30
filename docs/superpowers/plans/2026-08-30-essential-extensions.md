# The Four "Nearly Essential" Extensions — Implementation Plan

**Goal:** History retention, a timeline device picker sourced from the DB,
ringing a device, and visible semantic locations — see the spec for the
full rationale and the upstream/protocol findings that shaped this.

**Architecture:** One new nullable column on `device_settings`
(`last_known_name`), three new `LocationStore` methods, two new
`service/locations.py` wrappers around an already-implemented upstream
action, two new endpoints, one bugfix, and matching frontend/doc changes.
No new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-08-30-essential-extensions-design.md`

**Tech Stack:** unchanged — Python 3.11, FastAPI/Starlette, SQLite
(stdlib `sqlite3`), vanilla JS + Leaflet, pytest.

## Tasks

1. **`service/store.py`**
   - `_migrate_schema(conn)`: `ALTER TABLE device_settings ADD COLUMN
     last_known_name TEXT` when missing (checked via `PRAGMA
     table_info`), called from `_connect()` after `executescript(_SCHEMA)`.
   - `prune_older_than(cutoff_ts) -> int`: `DELETE FROM locations WHERE ts
     < ?`, same lock/error pattern as the other writes.
   - `set_last_seen_name(device_id, name)`: upsert into `device_settings`,
     touching only `last_known_name` (no-op on falsy `name`).
   - `known_devices() -> list[dict]`: union of `locations` device ids and
     `device_settings` device ids; name priority manual override →
     `last_known_name` → device id; sorted most-recently-seen first, never
     -seen last.

2. **`service/augment.py`** — `augment_device()` calls
   `store.set_last_seen_name(device["id"], device["default_name"])` right
   after `default_name` is established, unconditionally (geo, semantic, or
   error entries all get it).

3. **`service/locations.py`**
   - Bugfix: the semantic branch of `_extract_locations()` returns
     `"place_name"` instead of `"name"` (prevents `poll_all_devices()`'s
     `dict.update()` from clobbering the device's own name).
   - `start_sound(canonic_device_id) -> bool` / `stop_sound(...) -> bool`,
     via a shared `_send_sound_request()` using
     `NovaApi.ExecuteAction.PlaySound.sound_request.create_sound_request`,
     `FcmReceiver`, `nova_request` — same callback-cleanup discipline as
     `_fetch_device_update`, `SOUND_REQUEST_GRACE_SECONDS = 2` sleep
     instead of a response wait. Catches exceptions, logs, returns `False`.

4. **`service/main.py`**
   - `GFM_HISTORY_RETENTION_DAYS` (env, default unset → `0` →
     disabled), `_maybe_prune_history()` (gated on a remembered
     `_last_prune["at"]`, at most once a day), called at the end of every
     `_poll_loop()` iteration.
   - `GET /api/devices` → `{"devices": _store.known_devices()}`.
   - `POST /api/devices/{id}/ring` / `POST /api/devices/{id}/ring/stop`,
     both `Depends(block_cross_site)`, plain sync `def` (FastAPI runs
     these in its threadpool automatically). 502 with a clear `detail` on
     a `False` return from the `locations` wrapper.

5. **Frontend**
   - `web/index.html`: 🔔 ring button next to the existing ✎ edit button
     (`.device-actions` wrapper, `setRinging()` helper — toggles a
     `.ringing` class/label, 30 s client-side auto-reset since Google times
     the sound out on its own). `renderList()` shows `{place} · {time}`
     for a semantic device instead of a bare timestamp, `place_name`
     escaped through `escapeHtml()` exactly like every other server string
     rendered via `innerHTML` in this file (it can originate from a
     user-edited Google Maps place label, so it gets the same treatment as
     the device name / error text / geocoded address).
   - `web/timeline.html`: `loadDevices()` now fetches `/api/devices` (the
     `<select>` source) and `/api/locations` (pin-colour map only) in
     parallel.
   - `web/app.js`: `ring`, `stop_ring`, `at_place` strings, EN + DE.

6. **Tests**
   - `service/tests/test_store.py`: `TestPruning`, `TestKnownDevices`
     (including a raw-`sqlite3`-created pre-migration DB to actually
     exercise the `ALTER TABLE` path, not just a fresh schema that already
     has the column).
   - `service/tests/test_augment.py`: `TestSemanticLocations` (name not
     clobbered, no bogus `locations` row for a semantic fix),
     `TestLastKnownNamePersistence`.
   - `service/tests/test_api.py`: `locations` stub gains
     `start_sound`/`stop_sound` (default `True`, overridable per test for
     the failure path); new tests for `/api/devices`, ring/stop-ring
     (success, failure, CSRF), the semantic-name regression, retention
     enabled-vs-default-off (with an explicit `_last_prune["at"] = 0.0`
     reset in the test to sidestep the background poll loop's own prune
     call already having consumed the daily gate), plus light
     `test_real_*` checks that the ring button and the `/api/devices`
     fetch actually made it into the real HTML files.

7. **Docs** — `README.md` (Web UI bullets, endpoint list, env var table,
   Known limitations — the retention and device-picker limitations are
   reworded/removed), `.env.example`, `SECURITY.md`.

## Verification

`cd findmy-map-production && .venv/bin/python -m pytest -q` — full suite
green (174 tests: 154 before this initiative + 20 new/split out for it).
Ring additionally needs a manual check against a real device (no delivery
confirmation exists in the protocol to assert on in an automated test).
