"""Full per-device location history, backed by SQLite.

The main map only needs the last few fixes, but the timeline page needs
the complete track. Keeping every fix in a JSON file that is rewritten on
every poll doesn't scale, so history lives in a single SQLite database
(``sqlite3`` is in the standard library -- no new dependency).

One fix per (device, timestamp) is stored; a second report for a
timestamp already on file is ignored.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path

log = logging.getLogger("findmy-map")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS locations (
    device_id TEXT    NOT NULL,
    ts        INTEGER NOT NULL,
    lat       REAL    NOT NULL,
    lon       REAL    NOT NULL,
    accuracy  REAL,
    PRIMARY KEY (device_id, ts)
);

CREATE TABLE IF NOT EXISTS device_settings (
    device_id TEXT PRIMARY KEY,
    name      TEXT,   -- NULL: no name override, use the polled name
    color     TEXT    -- NULL: no colour override, fall back to env/palette
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    qlat       REAL NOT NULL,   -- query lat/lon rounded to 4 decimals (~11 m)
    qlon       REAL NOT NULL,
    label      TEXT,            -- short human label
    address    TEXT,            -- full display name
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY (qlat, qlon)
);
"""

_GEOCODE_PRECISION = 4


class LocationStore:
    def __init__(self, path):
        self._lock = threading.Lock()
        self._write_warned = False
        self._conn = self._connect(str(path))

    def _connect(self, path):
        try:
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            return conn
        except sqlite3.Error as exc:
            log.error(
                "Cannot open history DB at %s (%s); using an in-memory DB -- "
                "the location history will NOT survive a restart.",
                path,
                exc,
            )
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.executescript(_SCHEMA)
            conn.commit()
            return conn

    def close(self):
        with self._lock:
            self._conn.close()

    # -- writes ---------------------------------------------------------

    def add(self, device_id, point):
        """Store one geo fix. Points missing coordinates or a time are ignored."""
        lat = point.get("latitude")
        lon = point.get("longitude")
        ts = point.get("time")
        if lat is None or lon is None or ts is None:
            return
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR IGNORE INTO locations "
                    "(device_id, ts, lat, lon, accuracy) VALUES (?, ?, ?, ?, ?)",
                    (device_id, int(ts), float(lat), float(lon), point.get("accuracy")),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                if not self._write_warned:
                    log.warning(
                        "Could not write to history DB: %s (further write "
                        "errors suppressed).",
                        exc,
                    )
                    self._write_warned = True

    def set_setting(self, device_id, name=None, color=None):
        """Upsert a device's display-name / pin-colour override.

        Empty strings are treated as "no override" and stored as NULL.
        """
        name = name or None
        color = color or None
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO device_settings (device_id, name, color) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(device_id) DO UPDATE SET name = ?, color = ?",
                    (device_id, name, color, name, color),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                if not self._write_warned:
                    log.warning(
                        "Could not write device settings: %s (further write "
                        "errors suppressed).",
                        exc,
                    )
                    self._write_warned = True

    def get_settings(self):
        """All device overrides as ``{device_id: {"name": ..., "color": ...}}``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT device_id, name, color FROM device_settings"
            ).fetchall()
        return {r[0]: {"name": r[1], "color": r[2]} for r in rows}

    # -- reverse-geocode cache ---------------------------------------------

    def geocode_get(self, lat, lon):
        """Cached entry for a coordinate (rounded), or ``None`` on a miss.

        A row with ``label``/``address`` both ``None`` is a *negative* cache
        entry (a lookup that failed); ``fetched_at`` lets callers decide when
        to retry it.
        """
        qlat = round(lat, _GEOCODE_PRECISION)
        qlon = round(lon, _GEOCODE_PRECISION)
        with self._lock:
            row = self._conn.execute(
                "SELECT label, address, fetched_at FROM geocode_cache "
                "WHERE qlat = ? AND qlon = ?",
                (qlat, qlon),
            ).fetchone()
        if row is None:
            return None
        return {"label": row[0], "address": row[1], "fetched_at": row[2]}

    def geocode_put(self, lat, lon, label, address):
        qlat = round(lat, _GEOCODE_PRECISION)
        qlon = round(lon, _GEOCODE_PRECISION)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO geocode_cache (qlat, qlon, label, address, fetched_at) "
                    "VALUES (?, ?, ?, ?, strftime('%s','now')) "
                    "ON CONFLICT(qlat, qlon) DO UPDATE SET "
                    "label = excluded.label, address = excluded.address, "
                    "fetched_at = excluded.fetched_at",
                    (qlat, qlon, label, address),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                if not self._write_warned:
                    log.warning("Could not write geocode cache: %s", exc)
                    self._write_warned = True

    def migrate_json(self, json_path):
        """Import a legacy ``history.json`` (``{device_id: [points]}``) once.

        The file is renamed to ``*.migrated`` afterwards so it is imported
        only a single time. Missing or unreadable files are ignored.
        """
        json_path = Path(json_path)
        if not json_path.exists():
            return
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read legacy history file %s: %s", json_path, exc)
            return

        if isinstance(data, dict):
            imported = 0
            for device_id, points in data.items():
                for point in points or []:
                    self.add(device_id, point)
                    imported += 1
            log.info("Migrated %d legacy history point(s) into %s.", imported, "the DB")

        try:
            json_path.rename(json_path.with_name(json_path.name + ".migrated"))
        except OSError as exc:
            log.warning("Could not rename migrated history file %s: %s", json_path, exc)

    # -- reads ---------------------------------------------------------

    def recent(self, device_id, n=5):
        """The newest ``n`` fixes for a device, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, lat, lon, accuracy FROM locations "
                "WHERE device_id = ? ORDER BY ts DESC LIMIT ?",
                (device_id, n),
            ).fetchall()
        return [_row_to_point(r) for r in reversed(rows)]

    def range(self, device_id, start_ts, end_ts):
        """All fixes for a device with ``start_ts <= ts <= end_ts``, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, lat, lon, accuracy FROM locations "
                "WHERE device_id = ? AND ts >= ? AND ts <= ? ORDER BY ts ASC",
                (device_id, int(start_ts), int(end_ts)),
            ).fetchall()
        return [_row_to_point(r) for r in rows]


def _row_to_point(row):
    ts, lat, lon, accuracy = row
    return {"time": ts, "latitude": lat, "longitude": lon, "accuracy": accuracy}
