import pytest

from geocode import Geocoder, format_label
from store import LocationStore


@pytest.fixture
def store(tmp_path):
    s = LocationStore(tmp_path / "history.db")
    yield s
    s.close()


class TestFormatLabel:
    def test_named_poi_is_used_as_the_head(self):
        data = {
            "display_name": "Zoo Berlin, Hardenbergplatz, Berlin, 10787, Germany",
            "name": "Zoo Berlin",
            "address": {"tourism": "Zoo Berlin", "suburb": "Charlottenburg"},
        }
        label, address = format_label(data)
        assert label == "Zoo Berlin, Charlottenburg"
        assert address.startswith("Zoo Berlin, Hardenbergplatz")

    def test_road_and_house_number(self):
        data = {
            "display_name": "12, Example Street, Downtown, Berlin",
            "address": {"road": "Example Street", "house_number": "12", "suburb": "Downtown"},
        }
        label, _ = format_label(data)
        assert label == "Example Street 12, Downtown"

    def test_falls_back_to_display_name(self):
        data = {"display_name": "Somewhere, Nowhere", "address": {}}
        label, address = format_label(data)
        assert label == "Somewhere"
        assert address == "Somewhere, Nowhere"

    def test_empty_input(self):
        assert format_label({}) == (None, None)
        assert format_label(None) == (None, None)


class TestGeocoder:
    def test_disabled_when_no_base_url(self, store):
        g = Geocoder(store, base_url="")
        assert g.enabled is False
        g.enqueue(52.5, 13.4)  # no-op, must not raise

    def test_lookup_delegates_to_the_store_cache(self, store):
        store.geocode_put(52.5, 13.4, "X", "X, City")
        g = Geocoder(store, base_url="https://example.test")
        got = g.lookup(52.5, 13.4)
        assert got["label"] == "X" and got["address"] == "X, City"

    def test_process_one_fetches_and_caches(self, store):
        calls = []

        def fake_get(url):
            calls.append(url)
            return {"display_name": "Square 1, District, City",
                    "address": {"road": "Square", "house_number": "1", "suburb": "District"}}

        g = Geocoder(store, base_url="https://example.test", http_get=fake_get)
        assert g.enqueue(52.5211, 13.4066) is True
        assert g._drain_one() == (True, True)

        assert len(calls) == 1 and "lat=52.5211" in calls[0]
        got = g.lookup(52.5211, 13.4066)
        assert got["label"] == "Square 1, District"
        assert got["address"] == "Square 1, District, City"

    def test_enqueue_skips_already_cached_coordinates(self, store):
        store.geocode_put(52.5, 13.4, "Here", "Here")
        g = Geocoder(store, base_url="https://example.test")
        assert g.enqueue(52.5, 13.4) is False
        assert g.pending_count == 0

    def test_enqueue_dedupes_nearby_coordinates(self, store):
        g = Geocoder(store, base_url="https://example.test")
        g.enqueue(52.52001, 13.40501)
        g.enqueue(52.52004, 13.40498)  # same rounded key
        assert g.pending_count == 1

    def test_a_failing_fetch_is_negatively_cached_and_backed_off(self, store):
        def boom(url):
            raise RuntimeError("network down")

        g = Geocoder(store, base_url="https://example.test", http_get=boom)
        g.enqueue(52.5, 13.4)
        assert g._drain_one() == (True, False)
        assert g.lookup(52.5, 13.4)["label"] is None       # negative cache entry
        assert g.pending_count == 0
        assert g.enqueue(52.5, 13.4) is False              # within the negative TTL
        assert g.pending_count == 0

    def test_a_stale_negative_entry_is_retried(self, store):
        def boom(url):
            raise RuntimeError("still down")

        g = Geocoder(store, base_url="https://example.test", http_get=boom)
        g._negative_ttl = 0                                # expire negatives immediately
        g.enqueue(52.5, 13.4)
        g._drain_one()
        assert g.enqueue(52.5, 13.4) is True
        assert g.pending_count == 1

    def test_repeated_failures_increase_the_backoff(self, store):
        g = Geocoder(store, base_url="https://example.test",
                     http_get=lambda u: (_ for _ in ()).throw(RuntimeError("x")),
                     min_interval=1.0)
        g._negative_ttl = 0
        for _ in range(3):
            g.enqueue(52.5, 13.4)
            g._drain_one()
        assert g._consecutive_failures == 3
        assert g._backoff_seconds() > g._min_interval
