"""Full-source spatial API, confirmation persistence, and agent handoff."""

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from file_server.api.area_queries import register_area_routes
from tests.file_server.test_spatial import SQUARE, observation


@pytest.fixture
def area_app(tmp_path):
    rows = [observation("a"), observation("b"), observation("outside", x=114),
            observation("at250", length=250), observation("negative", label="not_aircraft_carrier")]
    app = FastAPI()
    register_area_routes(app, observations=lambda request: rows,
                         public_url=lambda request: "http://viewer:8002",
                         storage_root=lambda: tmp_path, source="demo")
    return app, rows


def test_named_areas_and_unknown_names_have_exactly_two_flows(area_app):
    app, _ = area_app
    with TestClient(app) as client:
        result = client.post("/area-queries", json={"area_name": "Biển Đông", "limit": 1}).json()
        assert result["status"] == "complete" and result["total"] == 5
        assert len(result["ships"]) == 1 and result["area_name"] == "Biển Đông"
        for name in ("Hoàng Sa", "gần nơi đó", "Trường Sa", "Scarborough"):
            result = client.post("/area-queries", json={"area_name": name}).json()
            assert result["status"] == "needs_drawing"
            assert "polygon" not in result and "total" not in result
            assert client.post(f"/area-queries/{result['selection_id']}/answer", json={}).status_code == 409
        assert client.get("/query-areas/hoang_sa").status_code == 404


def test_draw_confirm_reuse_and_restart(area_app, tmp_path):
    app, _ = area_app
    with TestClient(app) as client:
        selection = client.post("/area-queries", json={"area_name": "khu vực X", "length_gt_m": 250,
                                                       "classification": "aircraft_carrier", "limit": 1}).json()
        result = client.post(f"/area-queries/{selection['selection_id']}/confirm", json={"polygon": SQUARE}).json()
        assert result["total"] == result["possible_aircraft_carrier_count"] == 2
        assert len(result["ships"]) == 1
        assert result["area_id"] != selection["selection_id"]
        assert client.get(f"/area-queries/{result['area_id']}").status_code == 200
    with TestClient(app) as client:
        followup = client.post("/area-queries", json={"area_id": result["area_id"], "limit": 1, "offset": 2}).json()
        assert followup["total"] == 4 and len(followup["ships"]) == 1
        assert followup["ships"][0]["observation_id"] == "b"  # Stable id order within capture time.


def test_stale_area_and_bad_geometry_are_not_zero_results(area_app):
    app, rows = area_app
    with TestClient(app) as client:
        selection = client.post("/area-queries", json={"area_name": "X"}).json()
        url = f"/area-queries/{selection['selection_id']}/confirm"
        assert client.post(url, json={"polygon": {"type": "Polygon", "coordinates": []}}).status_code == 422
        rows.append(observation("new"))
        assert client.post(url, json={"polygon": SQUARE}).status_code == 409
        assert client.get("/area-queries/" + "0" * 32).status_code == 404


def test_confirmation_button_calls_agent_with_exact_area_and_filters(area_app, monkeypatch):
    import file_server.api.area_queries as area_queries

    calls = []

    async def answer(query, *, source):
        calls.append((query, source))
        return "Có 2 lượt phát hiện nghi là tàu sân bay."

    monkeypatch.setattr(area_queries, "ask_area_agent", answer)
    app, _ = area_app
    with TestClient(app) as client:
        result = client.post("/area-queries", json={"polygon": SQUARE, "length_gt_m": 250,
                                                    "classification": "aircraft_carrier"}).json()
        reply = client.post(f"/area-queries/{result['area_id']}/answer", json={})
        assert reply.status_code == 200 and reply.json()["answer"].startswith("Có 2")
    query, source = calls[0]
    assert source == "demo" and query["area_id"] == result["area_id"]
    assert query["classification"] == "aircraft_carrier" and query["length_gt_m"] == 250


def test_analysis_routes_and_strict_score_filter(area_app):
    app, rows = area_app
    for row in rows:
        row["confidence"] = .9
    with TestClient(app) as client:
        count = client.post("/area-queries", json={"polygon": SQUARE, "length_gt_m": 250,
            "carrier_score_gt": .8, "classification": "aircraft_carrier", "limit": 1}).json()
        assert count["total"] == 2 and len(count["ships"]) == 1
        mismatch = client.post("/observation-analyses", json={"analysis": "dimension_mismatch", "polygon": SQUARE}).json()
        assert mismatch["total"] == 1 and mismatch["ships"][0]["observation_id"] == "negative"
        pairs = client.post("/observation-analyses", json={"analysis": "similar_dimensions", "polygon": SQUARE, "limit": 1}).json()
        assert pairs["total"] == 2 and len(pairs["pairs"]) == 1
        assert pairs["count_unit"] == "observation_pairs"
        assert "ships" not in pairs
        followup = client.post("/observation-analyses", json={"analysis": "similar_dimensions",
            "area_id": pairs["area_id"], "offset": 1, "limit": 1}).json()
        assert followup["total"] == 2 and followup["pairs"] != pairs["pairs"]
        waiting = client.post("/observation-analyses", json={"analysis": "similar_dimensions", "area_name": "Hoàng Sa"}).json()
        assert waiting["status"] == "needs_drawing" and "total" not in waiting
        assert client.post("/observation-analyses", json={"analysis": "similar_dimensions",
            "classification": "aircraft_carrier"}).status_code == 422
        assert client.post("/area-queries", json={"carrier_score_gt": 1.1}).status_code == 422


def test_missed_candidates_require_dates_and_preserve_inclusive_gates(area_app):
    app, rows = area_app
    for row in rows:
        row.update(classification="not_aircraft_carrier", confidence=.01)
    with TestClient(app) as client:
        assert client.post("/missed-carrier-candidates", json={}).status_code == 422
        payload = {"observed_from": "2026-10-01", "observed_to": "2026-10-01", "polygon": SQUARE, "limit": 1}
        result = client.post("/missed-carrier-candidates", json=payload).json()
        assert result["total"] == 4 and len(result["ships"]) == 1
        assert result["filters"]["carrier_score_lte"] == .01
        assert result["source_snapshot_id"]
        payload.pop("polygon")
        assert client.post("/missed-carrier-candidates", json=payload).json()["total"] == 5
        assert client.post("/missed-carrier-candidates", json={**payload, "area_name": "Hoàng Sa"}).json()["status"] == "needs_drawing"
