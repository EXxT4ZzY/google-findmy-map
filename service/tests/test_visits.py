import pytest

from visits import detect_visits, haversine_m


def stay(lat, lon, start, count, step=120):
    """`count` points at ~(lat, lon) at `step`-second intervals from `start`."""
    return [
        {"latitude": lat + (i % 3) * 1e-5, "longitude": lon - (i % 2) * 1e-5,
         "time": start + i * step}
        for i in range(count)
    ]


class TestHaversine:
    def test_zero_distance_for_same_point(self):
        assert haversine_m(52.5, 13.4, 52.5, 13.4) == pytest.approx(0, abs=1e-6)

    def test_one_degree_of_latitude_is_about_111_km(self):
        assert haversine_m(52.0, 13.0, 53.0, 13.0) == pytest.approx(111_195, rel=0.01)


class TestDetectVisits:
    def test_a_long_stay_becomes_one_visit(self):
        pts = stay(52.5200, 13.4050, 1_000_000, count=16)  # 16 * 120s = 30 min
        visits = detect_visits(pts, radius_m=100, min_seconds=900)
        assert len(visits) == 1
        v = visits[0]
        assert v["start"] == 1_000_000
        assert v["end"] == 1_000_000 + 15 * 120
        assert v["point_count"] == 16
        assert v["lat"] == pytest.approx(52.5200, abs=1e-3)
        assert v["lon"] == pytest.approx(13.4050, abs=1e-3)

    def test_a_short_stay_is_ignored(self):
        pts = stay(52.52, 13.40, 1_000_000, count=4)  # 3 * 120 = 6 min < 15
        assert detect_visits(pts, min_seconds=900) == []

    def test_passing_through_produces_no_visits(self):
        pts = [
            {"latitude": 52.50 + i * 0.01, "longitude": 13.40, "time": 1_000_000 + i * 120}
            for i in range(12)
        ]
        assert detect_visits(pts, radius_m=100, min_seconds=900) == []

    def test_two_separate_stays_are_returned_in_order(self):
        a = stay(52.5000, 13.4000, 1_000_000, count=16)
        b = stay(52.5300, 13.4600, 1_000_000 + 10_000, count=20)
        visits = detect_visits(a + b, radius_m=100, min_seconds=900)
        assert len(visits) == 2
        assert visits[0]["lat"] == pytest.approx(52.5000, abs=1e-3)
        assert visits[1]["lat"] == pytest.approx(52.5300, abs=1e-3)
        assert visits[0]["end"] < visits[1]["start"]

    def test_min_seconds_boundary_is_inclusive(self):
        base = [
            {"latitude": 52.52, "longitude": 13.40, "time": 1_000_000},
            {"latitude": 52.52, "longitude": 13.40, "time": 1_000_000 + 900},
        ]
        assert len(detect_visits(base, min_seconds=900)) == 1
        base[1]["time"] = 1_000_000 + 899
        assert detect_visits(base, min_seconds=900) == []

    def test_points_without_coordinates_or_time_are_skipped(self):
        pts = stay(52.52, 13.40, 1_000_000, count=16)
        pts.insert(5, {"latitude": None, "longitude": None, "time": 1_000_600})
        pts.insert(9, {"latitude": 52.52, "longitude": 13.40, "time": None})
        visits = detect_visits(pts, min_seconds=900)
        assert len(visits) == 1

    def test_empty_input(self):
        assert detect_visits([]) == []
