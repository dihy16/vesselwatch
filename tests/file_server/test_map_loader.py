"""Shared map source preserves observations and uses model scores, never truth labels."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from file_server.area_models import AreaQueryInput
from file_server.config import DataSettings
from file_server.loader import load_store, registered_image
from file_server.map_bundle import load_bundle
from file_server.spatial import AreaGeometry, query_observations


@pytest.fixture
def map_data(tmp_path, monkeypatch):
    root = tmp_path / "images"
    (root / "nested").mkdir(parents=True)
    (root / "nested/crop.png").write_bytes(b"crop")
    rows = []
    # Truth is deliberately opposite to the saved prediction for the first crop.
    for identity, score, located in [("positive", .5, True), ("negative", .49, True),
                                      ("unknown", None, True), ("unlocated", .9, False)]:
        rows.append({"id": identity, "captured_at": "2025-12-07T03:10:00Z",
                     "latitude": 18.18 if located else None,
                     "longitude": 109.53 if located else None,
                     "image_path": "nested/crop.png",
                     "metadata": {"source_id": "source/" + identity,
                                  "ground_truth_label": "Carrier absent", "length_m": 300},
                     **({"prediction": {"carrier_score": score}} if score is not None else {})})
    data = SimpleNamespace(sources=rows, image_root=root)
    monkeypatch.setattr("file_server.map_loader.load_bundle", lambda _: (
        deepcopy(data), {"data_source": "map_bundle", "map_snapshot_id": "snapshot"}))
    settings = DataSettings(Path("unused"), Path("unused"), Path("unused"),
                            data_source="map_bundle", map_demo_dir=tmp_path)
    return settings


def test_all_crops_and_missing_fields_preserved(map_data):
    store = load_store(map_data)
    rows = {o.observation_id: o for o in store.observations}
    assert len(rows) == 4
    assert rows["positive"].classification == "aircraft_carrier"
    assert rows["negative"].classification == "not_aircraft_carrier"
    assert rows["unknown"].classification == "unknown"
    assert rows["unlocated"].position.latitude is None
    assert all(o.width_m is None for o in rows.values())
    assert store.summary["unknown_count"] == 1
    assert store.summary["missing_position_count"] == 1
    name, _ = store.images[rows["positive"].images[0].image_id]
    assert registered_image(store.image_root, name).read_bytes() == b"crop"
    assert registered_image(store.image_root, "../../escape.png") is None


def test_polygon_dates_and_classification_match_map_scores(map_data):
    rows = [o.model_dump() for o in load_store(map_data).observations]
    polygon = AreaGeometry({"type": "Polygon", "coordinates": [
        [[109, 18], [110, 18], [110, 19], [109, 19], [109, 18]]]})
    query = AreaQueryInput(observed_from="2025-01-01", observed_to="2025-12-31",
                           classification="aircraft_carrier")
    assert [r["observation_id"] for r in query_observations(rows, query, polygon)] == ["positive"]
    assert len(query_observations(rows, AreaQueryInput(), polygon)) == 3
    assert len(query_observations(rows, AreaQueryInput(min_width_m=10), polygon)) == 0
    assert len(query_observations(rows, AreaQueryInput(length_gt_m=300), polygon)) == 0


def test_missing_bundle_fails_instead_of_using_telegram(tmp_path):
    settings = DataSettings(Path("unused"), Path("unused"), Path("unused"),
                            data_source="map_bundle", map_demo_dir=tmp_path)
    with pytest.raises(ValueError, match="Missing exported map runtime"):
        load_store(settings)


def test_agent_client_accepts_complete_snapshot_with_unknown_fields(map_data):
    import httpx
    from ship_agent.file_server_client import load_observations
    rows = [o.model_dump() for o in load_store(map_data).observations]
    def respond(request):
        return httpx.Response(200, json={"is_mock": False, "timezone": "UTC", "total": 4,
                                       "limit": 100, "offset": 0, "observations": rows})
    assert load_observations(transport=httpx.MockTransport(respond)) == rows


def test_data_api_serves_map_images_and_slash_source_ids(map_data):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from file_server.app import create_app
    with TestClient(create_app(map_data)) as client:
        assert client.get("/health").json()["map_snapshot_id"] == "snapshot"
        page = client.get("/observations", params={"observed_from": "2025-01-01",
                                                   "observed_to": "2025-12-31"}).json()
        assert page["total"] == 4
        row = next(r for r in page["observations"] if r["observation_id"] == "positive")
        assert client.get(row["ship_url"]).json()["observation_id"] == "positive"
        image = client.get(row["images"][0]["url"])
        assert image.status_code == 200 and image.content == b"crop"


@pytest.mark.parametrize("threshold", [float("nan"), -0.1, 1.1, True])
def test_invalid_candidate_threshold_rejected(threshold):
    with pytest.raises(ValueError, match="MAP_CARRIER_THRESHOLD"):
        DataSettings(Path("m"), Path("i"), Path("p"), carrier_threshold=threshold)


def test_exported_bundle_matches_actual_runtime_when_available():
    bundle = Path(__file__).resolve().parents[2] / "data/exports/vessel-map-demo"
    if not bundle.is_dir():
        pytest.skip("Optional exported map data is not installed")
    data, provenance = load_bundle(bundle)
    store = load_store(DataSettings(Path("unused"), Path("unused"), Path("unused"),
                                    data_source="map_bundle", map_demo_dir=bundle))
    assert store.summary["map_snapshot_id"] == provenance["map_snapshot_id"]
    original = {r["id"]: r for r in data.sources}
    assert {o.observation_id for o in store.observations} == set(original)
    for observation in store.observations:
        row = original[observation.observation_id]
        score = row.get("prediction", {}).get("carrier_score")
        assert observation.confidence == score
        assert observation.observed_date == row["captured_at"][:10]
        assert observation.position.latitude == row["latitude"]
        assert observation.position.longitude == row["longitude"]
        expected = "unknown" if score is None else "aircraft_carrier" if score >= .5 else "not_aircraft_carrier"
        assert observation.classification == expected
    # Compare a regional/year query to the map's original score/coordinate records.
    polygon = AreaGeometry({"type": "Polygon", "coordinates": [
        [[108, 17], [112, 17], [112, 21], [108, 21], [108, 17]]]})
    query = AreaQueryInput(observed_from="2025-01-01", observed_to="2025-12-31",
                           classification="aircraft_carrier")
    expected = {r["id"] for r in data.sources
                if "2025-01-01" <= r["captured_at"][:10] <= "2025-12-31"
                and r.get("prediction", {}).get("carrier_score", -1) >= .5
                and r["latitude"] is not None and r["longitude"] is not None
                and polygon.covers(r["longitude"], r["latitude"])}
    actual = query_observations([o.model_dump() for o in store.observations], query, polygon)
    assert {r["observation_id"] for r in actual} == expected
