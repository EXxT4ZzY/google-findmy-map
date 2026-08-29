"""Group a device's raw location fixes into "visits" -- stretches where it
stayed within a small radius long enough to count as a stop at a place.

This is a deliberately simple online clustering: points are added to the
current stay while they fall within ``radius_m`` of its running centroid;
the first point outside closes the stay. A stay that spanned at least
``min_seconds`` becomes a visit.
"""

import math

EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def detect_visits(points, radius_m=100.0, min_seconds=900):
    """``points``: iterable of ``{latitude, longitude, time}`` ordered by time.

    Returns ``[{start, end, lat, lon, point_count}, ...]`` -- one entry per
    stay of at least ``min_seconds``, ``lat``/``lon`` being the stay's mean
    position.
    """
    visits = []
    cluster = []
    cx = cy = 0.0

    def flush():
        if len(cluster) < 2 or cluster[-1]["time"] - cluster[0]["time"] < min_seconds:
            return
        lat = sum(p["latitude"] for p in cluster) / len(cluster)
        lon = sum(p["longitude"] for p in cluster) / len(cluster)
        visits.append({
            "start": cluster[0]["time"],
            "end": cluster[-1]["time"],
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "point_count": len(cluster),
        })

    for p in points:
        if p.get("latitude") is None or p.get("longitude") is None or p.get("time") is None:
            continue
        if not cluster:
            cluster = [p]
            cx, cy = p["latitude"], p["longitude"]
            continue
        if haversine_m(cx, cy, p["latitude"], p["longitude"]) <= radius_m:
            cluster.append(p)
            cx = sum(q["latitude"] for q in cluster) / len(cluster)
            cy = sum(q["longitude"] for q in cluster) / len(cluster)
        else:
            flush()
            cluster = [p]
            cx, cy = p["latitude"], p["longitude"]

    flush()
    return visits
