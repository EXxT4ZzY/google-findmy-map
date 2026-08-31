"""Unit tests for the export formatters -- each output is parsed back with
a real parser (csv / json / ElementTree), never string-matched."""

import csv
import io
import json
from xml.etree import ElementTree as ET

import export

GPX_NS = "{http://www.topografix.com/GPX/1/1}"


def pts(*triples):
    """(ts, lat, lon) -> point dicts like LocationStore.range() returns."""
    return [{"time": t, "latitude": la, "longitude": lo, "accuracy": 5.0}
            for t, la, lo in triples]


TRACK = pts((1_700_000_000, 52.5, 13.4),
            (1_700_000_060, 52.51, 13.41),
            (1_700_000_120, 52.52, 13.42))

VISITS = [
    {"start": 1_700_000_000, "end": 1_700_003_600, "lat": 52.5, "lon": 13.4,
     "point_count": 12, "label": "Home", "address": "Alexanderstr. 1, Berlin"},
    {"start": 1_700_010_000, "end": 1_700_012_700, "lat": 52.49, "lon": 13.39,
     "point_count": 7, "label": None, "address": None},
]


class TestHistoryCsv:
    def test_header_and_rows(self):
        rows = list(csv.reader(io.StringIO(export.history_csv(TRACK))))
        assert rows[0] == ["time_iso", "time_unix", "latitude", "longitude", "accuracy"]
        assert len(rows) == 1 + len(TRACK)
        assert rows[1][0] == "2023-11-14T22:13:20Z"
        assert rows[1][1] == "1700000000"
        assert float(rows[1][2]) == 52.5

    def test_empty_track_is_just_the_header(self):
        rows = list(csv.reader(io.StringIO(export.history_csv([]))))
        assert rows == [["time_iso", "time_unix", "latitude", "longitude", "accuracy"]]

    def test_missing_accuracy_is_blank_not_the_string_none(self):
        p = [{"time": 1, "latitude": 1.0, "longitude": 2.0, "accuracy": None}]
        assert list(csv.reader(io.StringIO(export.history_csv(p))))[1][4] == ""


class TestHistoryGeojson:
    def test_is_a_linestring_feature_collection_in_lon_lat_order(self):
        d = json.loads(export.history_geojson(TRACK, "dev-1", "Phone"))
        assert d["type"] == "FeatureCollection"
        feat = d["features"][0]
        assert feat["geometry"]["type"] == "LineString"
        assert feat["geometry"]["coordinates"][0] == [13.4, 52.5]   # [lon, lat]
        assert feat["properties"]["name"] == "Phone"
        assert len(feat["properties"]["coordTimes"]) == len(TRACK)
        assert feat["properties"]["coordTimes"][0].endswith("Z")

    def test_empty_track_is_valid_json_with_no_coordinates(self):
        d = json.loads(export.history_geojson([], "dev-1", "Phone"))
        assert d["features"][0]["geometry"]["coordinates"] == []


class TestHistoryGpx:
    def test_parses_and_has_one_trkpt_per_point_with_a_time(self):
        root = ET.fromstring(export.history_gpx(TRACK, "Phone"))
        assert root.tag == f"{GPX_NS}gpx"
        trkpts = root.findall(f"{GPX_NS}trk/{GPX_NS}trkseg/{GPX_NS}trkpt")
        assert len(trkpts) == len(TRACK)
        assert trkpts[0].get("lat") == "52.5" and trkpts[0].get("lon") == "13.4"
        assert trkpts[0].find(f"{GPX_NS}time").text == "2023-11-14T22:13:20Z"

    def test_empty_track_is_valid_gpx_with_an_empty_segment(self):
        root = ET.fromstring(export.history_gpx([], "Phone"))
        assert root.findall(f"{GPX_NS}trk/{GPX_NS}trkseg/{GPX_NS}trkpt") == []

    def test_a_name_with_xml_metacharacters_is_escaped(self):
        xml = export.history_gpx(TRACK, "dev-1", name='A & B <weird>')
        root = ET.fromstring(xml)   # would raise if not escaped
        assert root.find(f"{GPX_NS}trk/{GPX_NS}name").text == "A & B <weird>"


class TestVisitsCsv:
    def test_header_rows_and_null_label_becomes_blank(self):
        rows = list(csv.reader(io.StringIO(export.visits_csv(VISITS))))
        assert rows[0] == ["start_iso", "end_iso", "duration_seconds",
                           "latitude", "longitude", "label", "address", "point_count"]
        assert rows[1][2] == "3600"
        assert rows[1][5] == "Home"
        assert rows[2][5] == "" and rows[2][6] == ""

    def test_empty_visits(self):
        rows = list(csv.reader(io.StringIO(export.visits_csv([]))))
        assert len(rows) == 1


class TestVisitsGeojson:
    def test_point_features_with_properties(self):
        d = json.loads(export.visits_geojson(VISITS))
        assert [f["geometry"]["type"] for f in d["features"]] == ["Point", "Point"]
        assert d["features"][0]["geometry"]["coordinates"] == [13.4, 52.5]
        assert d["features"][0]["properties"]["duration_s"] == 3600
        assert d["features"][1]["properties"]["label"] is None


class TestVisitsGpx:
    def test_one_wpt_per_visit_named_only_when_labelled(self):
        root = ET.fromstring(export.visits_gpx(VISITS))
        wpts = root.findall(f"{GPX_NS}wpt")
        assert len(wpts) == 2
        assert wpts[0].find(f"{GPX_NS}name").text == "Home"
        assert wpts[1].find(f"{GPX_NS}name") is None   # unlabelled visit
        assert wpts[0].find(f"{GPX_NS}time").text == "2023-11-14T22:13:20Z"


class TestFilenameSlug:
    def test_keeps_safe_chars_and_replaces_the_rest(self):
        assert export.filename_slug("Peter's iPhone 15") == "Peter-s-iPhone-15"
        assert export.filename_slug("  ") == "export"
        assert len(export.filename_slug("x" * 200)) == 60
