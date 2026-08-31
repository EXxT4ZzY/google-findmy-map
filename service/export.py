"""Turn a device's history / visits into a downloadable file.

Pure functions, standard library only. ``points`` dicts are exactly what
``LocationStore.range()`` returns (``time`` / ``latitude`` / ``longitude``
/ ``accuracy``); ``visits`` dicts are what ``visits.detect_visits()``
returns (``start`` / ``end`` / ``lat`` / ``lon`` / ``point_count``),
optionally with ``label`` / ``address`` attached from the geocode cache.

Each ``*_FORMATS`` dict maps a ``format`` query value to
``(formatter, media_type, file_extension)``.
"""

import csv
import io
import json
import re
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

_GPX_NS = "http://www.topografix.com/GPX/1/1"


def _iso(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(x):
    """Trim a float for text output without scientific notation surprises."""
    return f"{x:.7f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def _xml_str(root):
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def filename_slug(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (s or "").strip()).strip("-")
    return (s or "export")[:60]


# -- history -----------------------------------------------------------------

def history_csv(points, device=None, name=None):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time_iso", "time_unix", "latitude", "longitude", "accuracy"])
    for p in points:
        w.writerow([
            _iso(p["time"]), int(p["time"]),
            _num(p["latitude"]), _num(p["longitude"]),
            "" if p.get("accuracy") is None else _num(p["accuracy"]),
        ])
    return buf.getvalue()


def history_geojson(points, device=None, name=None):
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[p["longitude"], p["latitude"]] for p in points],
            },
            "properties": {
                "device": device,
                "name": name,
                "coordTimes": [_iso(p["time"]) for p in points],
            },
        }],
    }
    return json.dumps(fc, ensure_ascii=False, indent=1)


def history_gpx(points, device=None, name=None):
    gpx = ET.Element("gpx", {"version": "1.1", "creator": "findmy-map", "xmlns": _GPX_NS})
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = name or "track"
    seg = ET.SubElement(trk, "trkseg")
    for p in points:
        pt = ET.SubElement(seg, "trkpt",
                           {"lat": _num(p["latitude"]), "lon": _num(p["longitude"])})
        ET.SubElement(pt, "time").text = _iso(p["time"])
    return _xml_str(gpx)


# -- visits ----------------------------------------------------------------

_VISIT_FIELDS = ["start_iso", "end_iso", "duration_seconds",
                 "latitude", "longitude", "label", "address", "point_count"]


def _visit_row(v):
    return {
        "start_iso": _iso(v["start"]),
        "end_iso": _iso(v["end"]),
        "duration_seconds": int(v["end"]) - int(v["start"]),
        "latitude": _num(v["lat"]),
        "longitude": _num(v["lon"]),
        "label": v.get("label") or "",
        "address": v.get("address") or "",
        "point_count": v.get("point_count", ""),
    }


def visits_csv(visits):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_VISIT_FIELDS)
    w.writeheader()
    for v in visits:
        w.writerow(_visit_row(v))
    return buf.getvalue()


def visits_geojson(visits):
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [v["lon"], v["lat"]]},
            "properties": {
                "start": _iso(v["start"]),
                "end": _iso(v["end"]),
                "duration_s": int(v["end"]) - int(v["start"]),
                "label": v.get("label"),
                "address": v.get("address"),
                "point_count": v.get("point_count"),
            },
        } for v in visits],
    }
    return json.dumps(fc, ensure_ascii=False, indent=1)


def visits_gpx(visits):
    gpx = ET.Element("gpx", {"version": "1.1", "creator": "findmy-map", "xmlns": _GPX_NS})
    for v in visits:
        wpt = ET.SubElement(gpx, "wpt", {"lat": _num(v["lat"]), "lon": _num(v["lon"])})
        if v.get("label"):
            ET.SubElement(wpt, "name").text = v["label"]
        ET.SubElement(wpt, "time").text = _iso(v["start"])
        desc = " · ".join(x for x in (
            v.get("address"), f'{int(v["end"]) - int(v["start"])} s') if x)
        if desc:
            ET.SubElement(wpt, "desc").text = desc
    return _xml_str(gpx)


HISTORY_FORMATS = {
    "csv":     (history_csv,     "text/csv; charset=utf-8", "csv"),
    "geojson": (history_geojson, "application/geo+json",    "geojson"),
    "gpx":     (history_gpx,     "application/gpx+xml",      "gpx"),
}

VISIT_FORMATS = {
    "csv":     (visits_csv,     "text/csv; charset=utf-8", "csv"),
    "geojson": (visits_geojson, "application/geo+json",    "geojson"),
    "gpx":     (visits_gpx,     "application/gpx+xml",      "gpx"),
}
