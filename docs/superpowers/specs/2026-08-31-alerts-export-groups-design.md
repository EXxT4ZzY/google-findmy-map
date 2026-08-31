# Design: poll-failure alert, data export, device groups

Three independent features from the feature backlog, all rated "Wichtig".
No new runtime dependency; all three are stdlib + the existing stack
(FastAPI, SQLite, vanilla JS + Leaflet).

---

## 1. Visible alert on sustained polling failure

### Problem

The service's whole job is continuous background tracking. When polling
breaks (expired `secrets.json`, an upstream protocol change, FCM trouble)
the only signal today is a thin red line in the status box that is easy to
miss — you discover it when you need a location and it is stale.
`service/main.py` already tracks `_state["last_error"]` and clears it on a
good cycle; it just is not surfaced prominently and a single transient
hiccup would alarm.

### Approach

- A **consecutive-failure counter** in `_state`. A poll cycle counts as
  failed when `locations.poll_all_devices()` raises **or** returns a
  non-empty list in which *every* device carries an `"error"` key — the
  latter is how an expired token actually manifests (the vendored library
  reports per-device `fetch_failed` rather than raising). An empty account
  (`[]`) is not a failure.
- Alert fires at `GFM_POLL_ALERT_AFTER` (default **3**) consecutive
  failures — ~6 min at the default 120 s interval: past a single hiccup,
  well before you would care.
- The poll body is extracted into `_run_poll_cycle() -> bool`, which also
  catches `SystemExit` — closing a latent gap where a vendored-library
  `exit()` inside `list_devices()` silently kills the poll thread.
- `GET /api/locations` gains `poll_alert: bool` and
  `poll_interval_seconds: int`. A new **public** `GET /api/health` returns
  `{ok, poll_alert, last_poll, consecutive_failures, poll_interval_seconds}`
  with **no error string** — safe for external uptime monitors, and the
  data source for the timeline page's banner (which otherwise does not
  poll).
- Frontend: a fixed full-width banner (`#poll-alert`) at the top of
  `index.html` and `timeline.html`, styled with `--error`, showing the
  last successful update time and (on index, from `/api/locations`) the
  raw error. It clears itself when a cycle succeeds. A client-side
  fallback also shows it when `last_poll` is older than
  `(GFM_POLL_ALERT_AFTER + 1) × poll_interval_seconds` (loop hung / server
  unreachable).

### Non-goals

Outbound notifications (webhook / ntfy / Pushover). That stays bundled
with the deferred geofencing feature in the backlog.

---

## 2. History / visit export (GPX / GeoJSON / CSV)

### Problem

`SECURITY.md` tells operators to back up `history.db`, but the app gives
no structured way to extract the data — for backup, or for analysis in
QGIS / Google Earth / a script.

### Approach

- A new pure-function module `service/export.py` (stdlib `csv`, `json`,
  `xml.etree.ElementTree`, `datetime`) with six formatters —
  `{history,visits} × {csv,geojson,gpx}` — operating on the exact dict
  shapes `LocationStore.range()` and `visits.detect_visits()` already
  return.
  - History GeoJSON: one `LineString` feature, `[lon,lat]` order,
    `properties.coordTimes` (GPX-style ISO array — QGIS / Felt read it).
  - History GPX: GPX 1.1 `<trk><trkseg><trkpt>` with `<time>`.
  - Visits GeoJSON: `Point` features with start/end/duration/label
    properties. Visits GPX: `<wpt>` waypoints.
- Two read-only endpoints:
  `GET /api/export/history?device=&start=&end=&format=` and
  `GET /api/export/visits?...`. `start`/`end` optional — omit both for the
  full history. Invalid `format` → 422. Unknown device → an empty but
  valid file, 200 (matches `/api/history`). `Content-Disposition:
  attachment` with a slugged filename. No `block_cross_site` — GET,
  non-mutating, same as `/api/history` / `/api/visits`; the auth gate and
  reverse proxy remain the boundary.
- Visits export attaches only **cached** geocode labels
  (`Geocoder.lookup()`); it never enqueues lookups.
- Frontend: download links on the timeline (track + visited places for the
  current device and range) and a "full history" export per device on the
  settings page.

---

## 3. Device groups / labels

### Problem

With more than a handful of devices the flat device list on the map and
the flat `<select>` on the timeline get unwieldy. Users want to organise
them ("Familie", "Fahrzeuge", …).

### Approach

- One nullable column `device_settings.device_group` (SQL-safe name —
  `group` is reserved; the API / UI key is `"group"`). Added via the
  existing `_migrate_schema()` `PRAGMA table_info` guard, exactly like
  `last_known_name` was.
- `set_setting()` gains a `group` parameter (same "write the column,
  `""` → NULL" semantics as name / colour). `get_settings()`,
  `known_devices()` and `augment_device()` carry it through.
  `PUT /api/devices/{id}` accepts `group` (trimmed, capped at 40 chars).
- Frontend:
  - `index.html` device list is bucketed by group. Headers render **only
    when at least one named group exists** — a install with no groups
    keeps today's flat list unchanged. Each group header is collapsible;
    the collapsed set is persisted per browser in `localStorage`, and a
    collapsed group also hides its pins from the map.
  - The device editor gets a free-text **Group** field with a
    `<datalist>` of the group names already in use.
  - The timeline device picker uses `<optgroup>` per named group.

### Non-goals

Per-group colours or icons; drag-and-drop reordering; group-level ring /
export actions.
