# r/selfhosted post draft

**Suggested title:**
findmy-map – self-hosted web map + location history for your Google Find My devices

**Flair:** Release / Product Announcement

---

**Body:**

I use [GoogleFindMyTools](https://github.com/leonboe1/GoogleFindMyTools) to pull locations for my phone and a couple of Find My Device trackers, but it only prints a Google Maps link per device in the terminal. I wanted an always-on map and some history, so I built **findmy-map**.

It runs as a small add-on container **next to** an existing GoogleFindMyTools container. It bind-mounts just that container's `Auth/secrets.json`, so there's no second login and token refreshes stay in sync.

What it does:

- Leaflet + OpenStreetMap map of every device, each with its own pin colour and a short trailing track
- **Timeline page:** full track for any device + date range, plus a text list of *visited places* (address, arrival–departure, duration), reverse-geocoded through Nominatim
- Editable device names / pin colours, stored in SQLite alongside the full history
- Light/dark themes, EN/DE, and a mobile layout with the device list as a bottom sheet
- No API keys, no telemetry

Stack: FastAPI + a background poll thread, vanilla JS frontend, SQLite. ~1k lines. `linux/amd64` + `linux/arm64` image on GHCR.

```yaml
services:
  findmy-map:
    image: ghcr.io/exxt4zzy/google-findmy-map:0.1.1
```

**Important:** it has **no authentication** – it's meant to sit behind whatever authenticating reverse proxy you already run. Also note the whole thing depends on GoogleFindMyTools, which reverse-engineers Google's Find My Device network; use it only for your own devices/account.

GitHub (screenshots + full `.env` reference): https://github.com/EXxT4ZzY/google-findmy-map

Feedback welcome, especially on the visited-places clustering – it's deliberately simple right now.

---

**Notes for posting:**
- Attach 2–3 images: `docs/img/map-dark.jpg`, `docs/img/timeline.jpg`, `docs/img/map-mobile.jpg` (reddit lets you add an image gallery to a text post).
- r/selfhosted asks that self-promotion posts are occasional and substantive – this qualifies as a "I built this" release post. Respond to comments.
- Good cross-post targets later: r/homelab, r/opensource, r/degoogle (the last one fits the "own your location data" angle).
