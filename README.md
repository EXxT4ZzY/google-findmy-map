# findmy-map

Shows the locations of the devices registered with Google "Find My Device"
(phone, ESP32 tracker, …) on a real map (Leaflet + OpenStreetMap) instead of
just a Google Maps link in the terminal. On top of that: a history track for a
chosen time range and a text-oriented list of visited places (similar to the
Google Timeline).

The service builds on the
[`leonboe1/GoogleFindMyTools`](https://github.com/leonboe1/GoogleFindMyTools)
library and is meant to run as an **add-on container next to an already
configured GoogleFindMyTools container**: it shares that container's
`Auth/secrets.json`, so **no separate login is required**.

> This project is not affiliated with Google or Apple. Use at your own risk and
> only for devices/accounts you are authorised to access.

## Screenshots

<img src="docs/img/map-dark.jpg" alt="Map view with several devices" width="100%">

<table>
<tr>
<td width="50%"><img src="docs/img/timeline.jpg" alt="Timeline: full track and a list of visited places" width="100%"></td>
<td width="50%"><img src="docs/img/edit-device.jpg" alt="Editing a device's name and pin colour" width="100%"></td>
</tr>
<tr>
<td><img src="docs/img/map-light.jpg" alt="Map view, light theme" width="100%"></td>
<td align="center"><img src="docs/img/map-mobile.jpg" alt="Mobile layout with the device list as a bottom sheet" height="420"></td>
</tr>
</table>

![Clicking through the map and the timeline](docs/img/demo.gif)

<sub>All screenshots use synthetic demo data (fictional devices moving around Berlin), not real location history.</sub>

## Requirements

- An already **logged-in** GoogleFindMyTools container; its
  `Auth/secrets.json` exists and holds valid tokens.

## Setup

Grab only `docker-compose.yml` and `.env.example` — the image is pulled from
GHCR, no clone or local build needed:

```bash
mkdir google-findmy-map && cd google-findmy-map
curl -O https://raw.githubusercontent.com/EXxT4ZzY/google-findmy-map/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/EXxT4ZzY/google-findmy-map/main/.env.example
# edit .env: GFM_SECRETS_FILE, GFM_DATA_DIR, PUID/PGID, PROXY_NETWORK
docker compose up -d
```

To build from source instead, clone the repo and flip `image:` back to
`build: .` in `docker-compose.yml`, then `docker compose up -d --build`.

Key `.env` values:

| Variable | Meaning |
|---|---|
| `GFM_SECRETS_FILE` | Host path to the **single** `secrets.json` of the existing GoogleFindMyTools container. Bind-mounted read-write so token refreshes stay in sync between both containers. Do **not** mount the whole `Auth/` folder — only this one file. |
| `GFM_DATA_DIR` | Host directory for this service's SQLite database (`history.db`). Holds raw location data — treat it as personal data. |
| `PUID` / `PGID` | Owner of the two paths above (and the UID the container runs as). Check with `stat -c '%u:%g' "$GFM_SECRETS_FILE"`. An init step chowns `GFM_DATA_DIR` to match. |
| `PROXY_NETWORK` | Name of the external Docker network your reverse proxy is on. |

All other (optional) variables are documented in `.env.example`.

## Web UI

- **Light/dark toggle** (☀/☾ in the header of both pages), remembered in the
  browser. In dark mode the OSM tiles are darkened via a CSS filter (building
  outlines / streets / labels stay intact); no API key.
- **Language toggle** (EN/DE in the header), also remembered in the browser.
- The map fills the screen; the device list sits on top as a **floating panel**
  (top right on desktop, sized to its content; a collapsible bottom sheet on
  narrow screens). Sorted by most recent location; clicking a row centres the
  map.
- Each device has its own pin colour; the last 5 positions are joined by a
  line.
- **Edit devices:** the ✎ button on each row → change the display name, pick a
  pin colour from a palette. **Default** clears both overrides.
- **Timeline** (`timeline.html`): pick a device and a from/to date → the full
  track as a line, plus a **list of visited places** (address, arrival–
  departure, duration) with numbered markers. A visit is only formed when the
  stored history actually contains several reports from *one* place (radius
  `GFM_VISIT_RADIUS_M`) spanning at least `GFM_VISIT_MIN_MINUTES` — with a still
  sparse history a note is shown, and it fills in over time.

## How it works

- `Dockerfile` clones `GoogleFindMyTools` (commit pinned via
  `ARG GFM_UPSTREAM_REF`) into `/app/vendor`.
- `docker-compose.yml` mounts only the single `secrets.json` into the vendored
  `Auth` folder — login data / token refresh shared rather than duplicated,
  without overwriting the rest of the vendored auth code. A `findmy-map-init`
  step (Alpine, root) chowns the data volume to `PUID:PGID` and exits.
- `service/locations.py` uses the library functions but returns structured
  data instead of only printing it.
- `service/main.py` — FastAPI + a background poll thread. Endpoints:
  `GET /api/locations` (incl. `palette`), `GET /api/history`,
  `GET /api/visits`, `POST /api/refresh`, `PUT /api/devices/{id}`. The mutating
  endpoints reject cross-site requests (Fetch Metadata).
- `service/store.py` — SQLite: full history (`add`/`recent`/`range` + a
  one-time `history.json` migration), device overrides, geocode cache.
- `service/colors.py` (pin colour, with validation), `service/augment.py`
  (track/name/colour per device), `service/visits.py` (clusters points into
  stays), `service/geocode.py` (reverse geocoding via Nominatim, ≤ 1
  request/1.1 s, negative cache + backoff).
- `web/index.html`, `web/timeline.html`, `web/app.css`, `web/app.js`.

## Environment variables

See `.env.example`. Summary:

| Variable | Default | Purpose |
|---|---|---|
| `GFM_POLL_INTERVAL_SECONDS` | `120` | Poll interval |
| `GFM_HISTORY_DB` | `/data/history.db` | SQLite DB (full history + settings + geocode cache) |
| `GFM_HISTORY_FILE` | `/data/history.json` | only for a one-time migration from an earlier version |
| `GFM_DEVICE_COLORS` | – | JSON `{id-or-name: hex/keyword}`. Priority: UI colour → env → palette |
| `GFM_NOMINATIM_URL` | public OSM Nominatim | reverse geocoding; **empty = off** |
| `GFM_GEOCODE_EMAIL` | – | contact email sent as the `email=` parameter (OSM policy) |
| `GFM_VISIT_RADIUS_M` / `GFM_VISIT_MIN_MINUTES` | `100` / `15` | definition of a "visited place" |

## Known limitations

- The location history grows unbounded (no cleanup logic). Fine for SQLite, but
  `history.db` grows over time.
- The timeline's device picker only lists devices returned by the current poll
  (removed devices disappear even though history data still exists).
- "Semantic locations" (named places without coordinates) get no marker.
- On an owner-key version change, `secrets.json` must be regenerated in the
  existing container.
- `secrets.json` is written non-atomically by both containers; a conflict on an
  exactly simultaneous token refresh is theoretically possible, in practice
  unlikely.

## License

[MIT](LICENSE)
