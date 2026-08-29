import json

import pytest

from store import LocationStore


def pt(lat=52.5, lon=13.4, time=1000, accuracy=10):
    return {"latitude": lat, "longitude": lon, "time": time, "accuracy": accuracy}


@pytest.fixture
def store(tmp_path):
    s = LocationStore(tmp_path / "history.db")
    yield s
    s.close()


class TestAdd:
    def test_add_then_recent_returns_the_point(self, store):
        store.add("dev", pt(time=1000))
        assert store.recent("dev") == [
            {"time": 1000, "latitude": 52.5, "longitude": 13.4, "accuracy": 10}
        ]

    def test_second_point_at_same_timestamp_is_ignored(self, store):
        store.add("dev", pt(time=1000, lat=52.5))
        store.add("dev", pt(time=1000, lat=99.9))
        points = store.recent("dev")
        assert len(points) == 1 and points[0]["latitude"] == 52.5

    def test_point_without_coordinates_or_time_is_skipped(self, store):
        store.add("dev", {"latitude": None, "longitude": None, "time": 1000})
        store.add("dev", {"latitude": 1, "longitude": 2, "time": None})
        assert store.recent("dev") == []

    def test_history_is_not_capped_at_five(self, store):
        for t in range(1, 11):
            store.add("dev", pt(time=t))
        assert len(store.range("dev", 0, 100)) == 10

    def test_recent_returns_the_newest_n_oldest_first(self, store):
        for t in (1, 2, 3, 4, 5, 6, 7):
            store.add("dev", pt(time=t))
        assert [p["time"] for p in store.recent("dev", 3)] == [5, 6, 7]

    def test_devices_do_not_share_history(self, store):
        store.add("a", pt(time=1))
        store.add("b", pt(time=2))
        assert [p["time"] for p in store.recent("a")] == [1]


class TestRange:
    def test_range_bounds_are_inclusive(self, store):
        for t in (10, 20, 30, 40):
            store.add("dev", pt(time=t))
        assert [p["time"] for p in store.range("dev", 20, 30)] == [20, 30]

    def test_range_with_no_data_in_window_is_empty(self, store):
        store.add("dev", pt(time=100))
        assert store.range("dev", 0, 50) == []


class TestPersistence:
    def test_data_survives_reopening_the_file(self, tmp_path):
        path = tmp_path / "history.db"
        first = LocationStore(path)
        first.add("dev", pt(time=1000))
        first.close()

        second = LocationStore(path)
        assert [p["time"] for p in second.recent("dev")] == [1000]
        second.close()


class TestMigration:
    def test_imports_legacy_json_and_renames_the_file(self, tmp_path):
        legacy = tmp_path / "history.json"
        legacy.write_text(json.dumps({"dev": [pt(time=1), pt(time=2)]}))

        store = LocationStore(tmp_path / "history.db")
        store.migrate_json(legacy)

        assert [p["time"] for p in store.recent("dev")] == [1, 2]
        assert not legacy.exists()
        assert (tmp_path / "history.json.migrated").exists()
        store.close()

    def test_migrating_a_missing_file_is_a_noop(self, store, tmp_path):
        store.migrate_json(tmp_path / "does-not-exist.json")  # must not raise

    def test_migrating_a_corrupt_file_is_a_noop(self, store, tmp_path):
        bad = tmp_path / "history.json"
        bad.write_text("{ not json")
        store.migrate_json(bad)  # must not raise
        assert store.recent("dev") == []


class TestDeviceSettings:
    def test_no_settings_by_default(self, store):
        assert store.get_settings() == {}

    def test_set_and_read_back_a_name_and_colour(self, store):
        store.set_setting("dev", name="Car", color="#ff0000")
        assert store.get_settings() == {"dev": {"name": "Car", "color": "#ff0000"}}

    def test_setting_is_upserted_not_duplicated(self, store):
        store.set_setting("dev", name="A", color="#111111")
        store.set_setting("dev", name="B", color="#222222")
        assert store.get_settings() == {"dev": {"name": "B", "color": "#222222"}}

    def test_empty_values_are_stored_as_no_override(self, store):
        store.set_setting("dev", name="A", color="#111111")
        store.set_setting("dev", name="", color="")
        assert store.get_settings() == {"dev": {"name": None, "color": None}}

    def test_settings_survive_reopen(self, tmp_path):
        path = tmp_path / "history.db"
        first = LocationStore(path)
        first.set_setting("dev", name="Car", color="#00ff00")
        first.close()
        second = LocationStore(path)
        assert second.get_settings() == {"dev": {"name": "Car", "color": "#00ff00"}}
        second.close()


class TestGeocodeCache:
    def test_miss_returns_none(self, store):
        assert store.geocode_get(52.5, 13.4) is None

    def test_put_then_get_roundtrip(self, store):
        store.geocode_put(52.52001, 13.40502, "Main St 1", "Main St 1, 10115 Berlin")
        got = store.geocode_get(52.52001, 13.40502)
        assert got["label"] == "Main St 1"
        assert got["address"] == "Main St 1, 10115 Berlin"
        assert isinstance(got["fetched_at"], int)

    def test_coordinates_are_rounded_so_nearby_lookups_hit(self, store):
        store.geocode_put(52.520011, 13.405021, "X", "X full")
        # ~5 m away -> rounds to the same 4-decimal key
        assert store.geocode_get(52.520044, 13.405049)["label"] == "X"

    def test_put_is_upserted(self, store):
        store.geocode_put(52.5, 13.4, "old", "old full")
        store.geocode_put(52.5, 13.4, "new", "new full")
        assert store.geocode_get(52.5, 13.4)["label"] == "new"

    def test_negative_entry_has_null_label_but_a_timestamp(self, store):
        store.geocode_put(52.5, 13.4, None, None)
        got = store.geocode_get(52.5, 13.4)
        assert got["label"] is None and isinstance(got["fetched_at"], int)


class TestReadonlyFallback:
    def test_unwritable_path_falls_back_to_in_memory(self, tmp_path):
        ro = tmp_path / "ro"
        ro.mkdir()
        ro.chmod(0o500)
        try:
            store = LocationStore(ro / "history.db")
            store.add("dev", pt(time=1))
            assert [p["time"] for p in store.recent("dev")] == [1]
        finally:
            ro.chmod(0o700)
