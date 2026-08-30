import pytest

from augment import augment_device
from colors import PALETTE
from store import LocationStore


@pytest.fixture
def store(tmp_path):
    s = LocationStore(tmp_path / "history.db")
    yield s
    s.close()


def geo_device(id="dev-1", name="Phone", lat=52.5, lon=13.4, time=2000, accuracy=12):
    return {
        "name": name, "id": id, "type": "geo",
        "latitude": lat, "longitude": lon, "time": time, "accuracy": accuracy,
        "status": "SEMANTIC", "is_own_report": True,
    }


def error_device(id="dev-1", name="Phone", error="no_response"):
    return {"name": name, "id": id, "error": error}


def semantic_device(id="dev-1", name="Phone", place_name="Home", time=2000):
    return {"name": name, "id": id, "type": "semantic", "place_name": place_name, "time": time}


class TestAugmentDevice:
    def test_records_geo_fix_into_the_store(self, store):
        augment_device(geo_device(time=2000), store, {})
        assert [p["time"] for p in store.recent("dev-1")] == [2000]

    def test_history_field_is_the_recent_track(self, store):
        store.add("dev-1", {"latitude": 52.5, "longitude": 13.4, "time": 1000, "accuracy": 9})
        result = augment_device(geo_device(time=2000), store, {})
        assert [p["time"] for p in result["history"]] == [1000, 2000]

    def test_history_field_is_capped_at_five_even_though_the_store_is_not(self, store):
        for t in range(1, 10):
            store.add("dev-1", {"latitude": 1, "longitude": 2, "time": t, "accuracy": 0})
        result = augment_device(error_device(), store, {})
        assert len(result["history"]) == 5

    def test_error_device_keeps_last_known_track_without_adding(self, store):
        store.add("dev-1", {"latitude": 52.5, "longitude": 13.4, "time": 1000, "accuracy": 9})
        result = augment_device(error_device(), store, {})
        assert [p["time"] for p in result["history"]] == [1000]

    def test_last_location_time_is_the_newest_stored_point(self, store):
        store.add("dev-1", {"latitude": 1, "longitude": 2, "time": 1000, "accuracy": 9})
        result = augment_device(error_device(), store, {})
        assert result["last_location_time"] == 1000

    def test_last_location_time_falls_back_to_current_fix_without_history(self, store):
        result = augment_device(dict(error_device(), time=None), store, {})
        assert result["last_location_time"] is None

    def test_color_override_by_name_is_applied(self, store):
        result = augment_device(geo_device(name="Phone"), store, {"Phone": "#abcdef"})
        assert result["color"] == "#abcdef"

    def test_fallback_index_selects_a_distinct_palette_colour(self, store):
        a = augment_device(geo_device(id="a"), store, {}, 0)["color"]
        b = augment_device(geo_device(id="b"), store, {}, 1)["color"]
        assert a == PALETTE[0] and b == PALETTE[1]

    def test_default_name_always_holds_the_polled_name(self, store):
        result = augment_device(geo_device(name="iPhone"), store, {})
        assert result["default_name"] == "iPhone"


class TestSemanticLocations:
    def test_place_name_does_not_overwrite_the_device_name(self, store):
        """Regression test: poll_all_devices() used to merge the semantic
        location's own "name" key straight into the device entry, silently
        replacing the device's display name with the place name."""
        result = augment_device(semantic_device(name="iPhone", place_name="Home"), store, {})
        assert result["name"] == "iPhone"
        assert result["place_name"] == "Home"

    def test_semantic_device_is_not_written_to_the_location_history(self, store):
        augment_device(semantic_device(), store, {})
        assert store.recent("dev-1") == []

    def test_last_location_time_falls_back_to_the_semantic_fix_time(self, store):
        result = augment_device(semantic_device(time=4000), store, {})
        assert result["last_location_time"] == 4000


class TestLastKnownNamePersistence:
    def test_polled_name_is_persisted_for_known_devices(self, store):
        augment_device(geo_device(id="dev-1", name="iPhone"), store, {})
        assert store.known_devices() == [
            {"id": "dev-1", "name": "iPhone", "last_seen": 2000}
        ]

    def test_a_manual_rename_is_not_overwritten_by_the_polled_name(self, store):
        store.set_setting("dev-1", name="Backpack")
        augment_device(geo_device(name="iPhone"), store, {}, settings=store.get_settings())
        assert store.known_devices()[0]["name"] == "Backpack"

    def test_semantic_only_devices_are_persisted_too(self, store):
        augment_device(semantic_device(id="dev-2", name="Watch"), store, {})
        assert any(d["id"] == "dev-2" and d["name"] == "Watch" for d in store.known_devices())


class TestDeviceSettingsOverrides:
    def test_custom_name_replaces_the_displayed_name(self, store):
        settings = {"dev-1": {"name": "Backpack", "color": None}}
        result = augment_device(geo_device(name="iPhone"), store, {}, settings=settings)
        assert result["name"] == "Backpack"
        assert result["default_name"] == "iPhone"

    def test_custom_colour_wins_over_env_and_palette(self, store):
        settings = {"dev-1": {"name": None, "color": "#0a0b0c"}}
        result = augment_device(
            geo_device(), store, {"dev-1": "#env000"}, 2, settings=settings
        )
        assert result["color"] == "#0a0b0c"

    def test_cleared_settings_fall_back_to_defaults(self, store):
        settings = {"dev-1": {"name": None, "color": None}}
        result = augment_device(geo_device(name="iPhone"), store, {}, 3, settings=settings)
        assert result["name"] == "iPhone"
        assert result["color"] == PALETTE[3]

    def test_flags_report_which_overrides_are_active(self, store):
        settings = {"dev-1": {"name": "Backpack", "color": None}}
        result = augment_device(geo_device(), store, {}, settings=settings)
        assert result["name_is_custom"] is True
        assert result["color_is_custom"] is False

    def test_re_augmenting_keeps_the_original_default_name(self, store):
        settings = {"dev-1": {"name": "Backpack", "color": None}}
        device = geo_device(name="iPhone")
        augment_device(device, store, {}, settings=settings)
        augment_device(device, store, {}, settings=settings)
        assert device["default_name"] == "iPhone" and device["name"] == "Backpack"
