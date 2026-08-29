"""Reverse-geocoding for the timeline's visited-places list.

Coordinates are turned into addresses via a Nominatim-compatible service
(OpenStreetMap's public Nominatim by default). Results are cached in the
SQLite store, and lookups that miss the cache are resolved by a single
background worker that makes at most one request every ~1.1 s, as the OSM
Nominatim usage policy requires.

A lookup that fails is written to the cache as a *negative* entry so it is
not retried until ``_negative_ttl`` seconds have passed, and repeated
failures back the worker off exponentially -- both so that an outage or a
misconfigured URL can't turn into a steady stream of requests that gets
the server's IP blocked.

Set ``GFM_NOMINATIM_URL`` to an empty string to disable geocoding entirely
(the timeline then labels visits by their coordinates).
"""

import logging
import threading
import time

log = logging.getLogger("findmy-map")

_USER_AGENT = "google-findmy-map (https://github.com/EXxT4ZzY/google-findmy-map; self-hosted)"
_NEGATIVE_TTL_SECONDS = 6 * 3600
_MAX_BACKOFF_SECONDS = 300


def format_label(data):
    """Turn a Nominatim reverse-geocode response into ``(short_label, full_address)``."""
    if not isinstance(data, dict):
        return None, None

    address = data.get("display_name")
    a = data.get("address") or {}

    name = (
        data.get("name")
        or a.get("amenity") or a.get("tourism") or a.get("shop") or a.get("office")
        or a.get("building")
    )
    road = a.get("road") or a.get("pedestrian") or a.get("footway") or a.get("path")
    house = a.get("house_number")
    locality = (
        a.get("suburb") or a.get("neighbourhood") or a.get("quarter")
        or a.get("city_district") or a.get("village") or a.get("town") or a.get("city")
    )

    if name:
        head = name
    elif road:
        head = f"{road} {house}" if house else road
    elif locality:
        head = locality
    else:
        head = address.split(",")[0].strip() if address else None

    if head and locality and locality.lower() not in head.lower():
        label = f"{head}, {locality}"
    else:
        label = head or address

    return label, address


class Geocoder:
    def __init__(self, store, base_url, email=None, http_get=None, min_interval=1.1):
        self._store = store
        self._base = base_url.rstrip("/") if base_url else ""
        self._email = email or None
        self._http_get = http_get or self._default_http_get
        self._min_interval = min_interval
        self._negative_ttl = _NEGATIVE_TTL_SECONDS

        self._lock = threading.Lock()
        self._pending = []          # FIFO list of (lat, lon)
        self._pending_keys = set()  # rounded keys queued or in flight
        self._consecutive_failures = 0
        self._stop = threading.Event()
        self._thread = None

    @property
    def enabled(self):
        return bool(self._base)

    @property
    def pending_count(self):
        with self._lock:
            return len(self._pending)

    def lookup(self, lat, lon):
        """Cached ``{"label", "address", "fetched_at"}`` for a coordinate, or ``None``."""
        return self._store.geocode_get(lat, lon)

    def enqueue(self, lat, lon):
        """Queue a coordinate for background geocoding.

        Returns ``True`` if it was actually queued, ``False`` if it is
        already resolved, already queued, or a recent failed lookup that
        we're still backing off from.
        """
        if not self.enabled:
            return False
        key = (round(lat, 4), round(lon, 4))
        with self._lock:
            if key in self._pending_keys:
                return False
            row = self._store.geocode_get(lat, lon)
            if row is not None:
                if row["label"] is not None:
                    return False
                age = time.time() - (row.get("fetched_at") or 0)
                if age < self._negative_ttl:
                    return False
            self._pending_keys.add(key)
            self._pending.append((lat, lon))
            return True

    def start(self):
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # -- internals -------------------------------------------------------

    def _backoff_seconds(self):
        if not self._consecutive_failures:
            return self._min_interval
        return min(self._min_interval * (2 ** self._consecutive_failures), _MAX_BACKOFF_SECONDS)

    def _run(self):
        while not self._stop.is_set():
            did, _ok = self._drain_one()
            self._stop.wait(self._backoff_seconds() if did else 1.0)

    def _drain_one(self):
        """Process the next queued coordinate.

        Returns ``(did_work, succeeded)``.
        """
        with self._lock:
            if not self._pending:
                return False, True
            lat, lon = self._pending.pop(0)
        ok = self._process_one(lat, lon)
        self._consecutive_failures = 0 if ok else self._consecutive_failures + 1
        return True, ok

    def _process_one(self, lat, lon):
        key = (round(lat, 4), round(lon, 4))
        try:
            data = self._http_get(self._reverse_url(lat, lon))
            label, address = format_label(data)
            self._store.geocode_put(lat, lon, label, address)
            ok = True
        except Exception as exc:
            log.warning("Reverse geocode request failed (%s); backing off.", exc)
            self._store.geocode_put(lat, lon, None, None)  # negative cache
            ok = False
        with self._lock:
            self._pending_keys.discard(key)
        return ok

    def _reverse_url(self, lat, lon):
        url = (
            f"{self._base}/reverse?format=jsonv2&lat={lat}&lon={lon}"
            "&zoom=18&addressdetails=1"
        )
        if self._email:
            url += f"&email={self._email}"
        return url

    def _default_http_get(self, url):
        import httpx

        resp = httpx.get(url, headers={"User-Agent": _USER_AGENT}, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
