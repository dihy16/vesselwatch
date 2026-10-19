"""Spatial semantics and input validation without live services or LLM calls."""

from copy import deepcopy
import gzip
import hashlib
import json

from pydantic import ValidationError
import pytest

from file_server.area_models import AreaQueryInput, AreaRequest
from file_server.spatial import (AREA_DATA, AREA_NAMES, AreaGeometry, UserPolygon,
                                 named_area, predefined_geometry, query_observations)


SQUARE = {"type": "Polygon", "coordinates": [[[110, 15], [112, 15], [112, 17], [110, 17], [110, 15]]]}


def observation(identity, x=111, y=16, length=300, label="aircraft_carrier", day="2026-10-01"):
    return {"observation_id": identity, "ship_id": "same-source-name", "observed_date": day,
            "observed_at": day + "T01:00:00+00:00", "position": {"longitude": x, "latitude": y},
            "length_m": length, "width_m": 60, "classification": label, "confidence": .1,
            "images": []}


def test_only_two_explicit_vietnamese_area_names_resolve():
    assert named_area("Toàn bộ Biển Đông") == "bien_dong"
    assert named_area("  vinh  bac bo ") == "vinh_bac_bo"
    assert named_area("Biển Đông") == "bien_dong"
    for name in ("Hoàng Sa", "Trường Sa", "Scarborough", "gần Vịnh Bắc Bộ", "khu vực X", None):
        assert named_area(name) is None
    assert set(AREA_NAMES.values()) == {"Biển Đông", "Vịnh Bắc Bộ"}


@pytest.mark.parametrize("point, expected", [((111, 16), True), ((110, 16), True),
                                            ((112, 17), True), ((109, 16), False)])
def test_polygon_includes_boundary(point, expected):
    assert AreaGeometry(SQUARE).covers(*point) is expected


def test_multipolygon_holes_and_disjoint_components():
    geometry = {"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
         [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]],
        [[[20, 20], [22, 20], [22, 22], [20, 22], [20, 20]]],
    ]}
    area = AreaGeometry(geometry)
    assert area.covers(1, 1)
    assert not area.covers(3, 3)
    assert area.covers(2, 3)  # Includes the polygon boundary, including hole edges.
    assert area.covers(21, 21)
    assert not area.covers(15, 15)


@pytest.mark.parametrize("ring", [
    [[110, 15], [112, 15], [112, 17]],  # Not closed.
    [[110, 15], [111, 16], [112, 17], [110, 15]],  # Zero area.
    [[0, 0], [4, 3], [0, 4], [3, 0], [0, 0]],  # Self intersection, nonzero signed area.
    [[110, 15], [112, 15], [112, 15], [110, 15]],
    [[181, 15], [182, 15], [182, 16], [181, 15]],
    [[110, 91], [112, 15], [112, 17], [110, 91]],
    [[179, 0], [-179, 0], [-179, 1], [179, 0]],
    [[110, 15], [float("nan"), 15], [112, 17], [110, 15]],
])
def test_rejects_invalid_drawn_polygons(ring):
    with pytest.raises(ValidationError):
        UserPolygon(coordinates=[ring])


@pytest.mark.parametrize("filters", [
    {"observed_from": "2026-02-30"}, {"observed_from": "2026-1-01"},
    {"observed_from": "2026-10-02", "observed_to": "2026-10-01"},
    {"observed_from": "2020-01-01", "observed_to": "2026-10-01"},
    {"area_name": "Biển Đông", "area_id": "a" * 32},
    {"min_length_m": 400, "max_length_m": 300}, {"length_gt_m": float("inf")},
    {"limit": 101}, {"offset": -1}, {"area_id": "../area"},
])
def test_rejects_invalid_filters(filters):
    with pytest.raises(ValidationError):
        AreaQueryInput(**filters)


def test_browser_can_supply_polygon_but_agent_schema_cannot():
    assert AreaRequest(polygon=SQUARE).polygon.type == "Polygon"
    with pytest.raises(ValidationError):
        AreaQueryInput(polygon=SQUARE)
    with pytest.raises(ValidationError):
        AreaRequest(polygon=SQUARE, area_name="Biển Đông")


def test_filter_complete_source_and_count_observations_not_ship_names():
    rows = [observation("a"), observation("b"), observation("outside", x=114),
            observation("at250", length=250), observation("negative", label="not_aircraft_carrier"),
            observation("old", day="2026-09-30"), observation("late", day="2026-10-03")]
    rows.append(deepcopy(rows[0]))
    query = AreaQueryInput(observed_from="2026-10-01", observed_to="2026-10-02",
                           length_gt_m=250, classification="aircraft_carrier", limit=1, offset=1)
    matches = query_observations(rows, query, AreaGeometry(SQUARE))
    assert [r["observation_id"] for r in matches] == ["a", "b"]
    assert all(r["confidence"] == .1 for r in matches)  # Stored label, no new score threshold.
    matches[0]["position"]["longitude"] = 0
    assert rows[0]["position"]["longitude"] == 111


def test_predefined_polygons_match_source_hashes_and_known_water_positions():
    metadata = json.loads((AREA_DATA / "sources.json").read_text(encoding="utf-8"))
    for source in metadata["sources"]:
        raw = gzip.decompress((AREA_DATA / source["asset"]).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == source["geometry_sha256"]
        assert json.loads(raw)["type"] == "MultiPolygon"
    assert predefined_geometry("bien_dong").covers(113, 16)
    assert predefined_geometry("vinh_bac_bo").covers(107.5, 20)
    assert not predefined_geometry("vinh_bac_bo").covers(113, 16)
    assert not predefined_geometry("bien_dong").covers(0, 0)
