# Plan: poll-failure alert, data export, device groups

**Spec:** `docs/superpowers/specs/2026-08-31-alerts-export-groups-design.md`

Three independent features. Recommended order: ascending complexity —
alert → export → groups. Each lands as
`feat:` (backend) → `test:` → `feat:` (frontend) → `docs:` commits.
Full suite must stay green (`python -m pytest -q`).

---

## Feature 1 — poll-failure alert

### `service/main.py`

- `POLL_ALERT_AFTER = int(os.environ.get("GFM_POLL_ALERT_AFTER", "3"))`.
- `_state` init gains `"consecutive_failures": 0`.
- Extract `_run_poll_cycle() -> bool` from `_poll_loop()`. Catches
  `(Exception, SystemExit)`. Failure → `last_error` set,
  `consecutive_failures += 1`. Returned list with every device errored →
  same, and `last_poll` untouched. Good cycle → `last_poll = now`,
  `last_error = None`, `consecutive_failures = 0`.
- `_poll_loop()` = `while True: _run_poll_cycle(); _maybe_prune_history();
  _refresh_now.wait(...); _refresh_now.clear()`.
- `get_locations()` payload gains `poll_alert` (>= threshold) and
  `poll_interval_seconds`.
- `GET /api/health` (add path to `PUBLIC_PATHS`): `{ok, poll_alert,
  last_poll, consecutive_failures, poll_interval_seconds}`, no error text.

### Frontend

- `web/index.html` + `web/timeline.html`: `<div id="poll-alert"
  class="poll-alert" hidden>` first child of `<body>`.
- `web/app.css`: `.poll-alert` fixed top bar (`--error`, white, ~32px);
  `html.has-poll-alert` shifts `#map` / `#sidebar` / `.auth-page` down.
- `web/app.js`: `window.FindMyMap.renderPollAlert(info)` helper; STRINGS
  `poll_alert`, `poll_alert_stale` (EN + DE). Staleness fallback when
  `last_poll` older than `(threshold + 1) × interval`.
- `index.html refresh()` calls it with the `/api/locations` payload.
- `timeline.html`: `setInterval(fetch('/api/health') → renderPollAlert,
  30000)`.

### Docs

`GFM_POLL_ALERT_AFTER` → `.env.example`, README env table. README endpoint
list: `/api/health`, new `/api/locations` fields. README "Known
limitations" reworded. SECURITY.md: `/api/health` is public, error-free.

### Tests — `service/tests/test_api.py`

Monkeypatch `client._main.locations.poll_all_devices`, call
`client._main._run_poll_cycle()` directly, assert `_state` +
`/api/locations` + `/api/health`. Cases: 2 vs 3 failures, recovery,
all-errored, `SystemExit` caught. `test_real_*`: `#poll-alert` in both
HTML files. (~8 tests.)

---

## Feature 2 — export

### `service/export.py` (new)

`history_csv/geojson/gpx(points, …)`, `visits_csv/geojson/gpx(visits)`,
`filename_slug(s)`, and `HISTORY_FORMATS` / `VISIT_FORMATS` dicts mapping
`format → (fn, media_type, ext)`. Stdlib only.

### `service/main.py`

- `GET /api/export/history?device=&start=&end=&format=` — optional range,
  both omitted → `_store.range(device, 0, now)`. 422 on bad format.
  `Response(content, media_type, headers={Content-Disposition})`.
- `GET /api/export/visits?...` — `visits_mod.detect_visits(...)` +
  `_geocoder.lookup()` for cached labels only.

### Frontend

- `web/timeline.html`: `#export` section after `#visits`, `hidden` until a
  track shows. `<a download>` links rebuilt in `show()` from device +
  `selectedRange()`. Visits row hidden when no visits.
- `web/settings.html`: "Data export" section — device `<select>` (from
  `/api/devices`) + 3 full-history links.
- `web/app.js`: STRINGS `s_export`, `export_track`, `export_visits`,
  `export_full_history`, `export_hint_full` (EN + DE).

### Docs

README "Web UI" + endpoint list. SECURITY.md one line. No env var.

### Tests

- `service/tests/test_export.py` (new): parse each format back
  (`csv.reader`, `json.loads` + GeoJSON structure + `[lon,lat]`,
  `ElementTree.fromstring` + GPX namespace + counts). Empty input → valid
  empty file. (~12 tests.)
- `service/tests/test_api.py`: both endpoints — status, `Content-Type`,
  `Content-Disposition`, bad format 422, unknown device 200, full-history
  path. (~8 tests.)
- `test_real_*`: `#export` in timeline, export section in settings.

---

## Feature 3 — device groups

### `service/store.py`

- `_SCHEMA` `device_settings` + `device_group TEXT`.
- `_migrate_schema()`: `ADD COLUMN device_group TEXT` when missing.
- `set_setting(device_id, name=None, color=None, group=None)` — 4th column
  in INSERT + `ON CONFLICT DO UPDATE`.
- `get_settings()` / `known_devices()` select and return `"group"`.

### `service/augment.py`

`device["group"] = override.get("group") or None`.

### `service/main.py`

- `DeviceSettingsBody.group: str | None = None`.
- `update_device`: `group = (body.group or "").strip()[:40]`, pass to
  `set_setting`, echo in response.

### Frontend

- `web/index.html`: `putDeviceSettings()` 4th arg; `buildEditor()` group
  field + `<datalist id="fmm-groups">`; `renderList()` buckets by group
  with collapsible headers (only when ≥1 named group);
  `localStorage['fmm.collapsedGroups']`; `drawDevice()` skips collapsed
  groups; `redrawFromCache()` on toggle.
- `web/timeline.html`: `loadDevices()` builds `<optgroup>`s.
- `web/app.js`: STRINGS `f_group`, `ungrouped` (EN + DE).
- `web/app.css`: `.group-header` (≥36px, caret rotates on `.collapsed`).

### Docs

README "Web UI" + "Edit devices" bullets. No env var.

### Tests

- `test_store.py` `TestDeviceGroups`: set/read; survives
  `set_last_seen_name`; `known_devices()` includes it; pre-migration DB
  gains the column. (~6 tests.)
- `test_augment.py`: `group` attached / `None` when unset. (~2 tests.)
- `test_api.py`: `PUT /api/devices/{id}` group persisted + echoed +
  trimmed; `/api/locations` + `/api/devices` carry it. (~4 tests.)
- `test_real_*`: `fmm-groups` datalist in index, `optgroup` in timeline,
  `f_group` in app.js.

---

## Verification

- `.venv/bin/python -m pytest -q` — full suite green (175 → ~220).
- Local synthetic-data run (`CLAUDE.md` "Running the service locally") +
  Playwright MCP browser: alert banner appears/clears; all export links
  download parseable files; groups bucket the list, collapse hides pins,
  timeline `<optgroup>`s work, flat list unchanged with no groups.
- Migration: open a pre-Feature-3 `history.db`, confirm `device_group` is
  added on startup without error.
