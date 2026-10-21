"""Hotspot routes preserve exact member IDs, shared areas and source/report revisions."""

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from file_server.area_queries import register_area_routes
from tests.file_server.test_carrier_hotspots import source_rows, scope, stub_labels
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def app_for(rows, tmp_path):
    app = FastAPI()
    register_area_routes(app, observations=lambda _: rows, public_url=lambda _: "http://public",
                         storage_root=lambda: tmp_path, source="file_server")
    return app


def test_full_summary_cluster_pagination_and_exact_member_pagination(tmp_path):
    with TestClient(app_for(source_rows(), tmp_path)) as client:
        query = scope(limit=1).model_dump()
        response = client.post("/carrier-hotspots", json=query)
        assert response.status_code == 200
        first = response.json()
        assert first["total"] == 2 and first["total_detections"] == 7
        assert first["clusters"][0]["detection_count"] == 3 and first["next_offset"] == 1
        second = client.post("/carrier-hotspots", json={**query, "offset": 1}).json()
        assert second["report_id"] == first["report_id"] and second["clusters"][0]["rank"] == 2
        detail_query = {**query, "report_id": first["report_id"], "cluster_id": first["clusters"][0]["cluster_id"]}
        detail = client.post("/carrier-hotspot-candidates", json=detail_query).json()
        assert detail["total"] == 3 and detail["dimension_candidate_count"] == 1
        assert detail["ships"][0]["observation_id"] == "a1"
        later = client.post("/carrier-hotspot-candidates", json={**detail_query, "offset": 1, "limit": 10}).json()
        assert {item["observation_id"] for item in later["ships"]} == {"a2", "a3"}
        assert client.post("/carrier-hotspot-candidates", json={**detail_query, "report_id": "f" * 64}).status_code == 409
        assert client.post("/carrier-hotspot-candidates", json={**detail_query, "cluster_id": "f" * 32}).status_code == 404
        assert client.post("/carrier-hotspot-candidates", json={**detail_query, "observed_to": "2025-01-02"}).status_code == 409


def test_area_and_snapshot_changes_require_rediscovery(tmp_path):
    rows = source_rows()
    with TestClient(app_for(rows, tmp_path)) as client:
        query = {**scope().model_dump(), "polygon": SQUARE}
        first = client.post("/carrier-hotspots", json=query).json()
        assert first["total_detections"] == 3 and first["total"] == 1
        assert first["unlocated_in_date_range_count"] == 1
        detail = {**query, "report_id": first["report_id"], "cluster_id": first["clusters"][0]["cluster_id"]}
        reused = client.post("/carrier-hotspot-candidates", json={**detail, "polygon": None,
                                                                 "area_id": first["area_id"]})
        assert reused.status_code == 200
        assert client.post("/carrier-hotspot-candidates", json={**detail, "polygon": None}).status_code == 409
        rows.append(row("new", x=111, y=16, day="2025-01-02"))
        assert client.post("/carrier-hotspot-candidates", json=detail).status_code == 409


def test_unknown_area_needs_drawing_dates_required_and_parameters_fixed(tmp_path):
    with TestClient(app_for(source_rows(), tmp_path)) as client:
        result = client.post("/carrier-hotspots", json={**scope().model_dump(), "area_name": "Hoàng Sa"}).json()
        assert result["status"] == "needs_drawing"
        assert client.post("/carrier-hotspots", json={}).status_code == 422
        for extra in ({"eps_km": 10}, {"min_samples": 5}, {"classification": "not_aircraft_carrier"}):
            assert client.post("/carrier-hotspots", json={**scope().model_dump(), **extra}).status_code == 422


def test_incompatible_cluster_engine_returns_service_error_not_zero_clusters(tmp_path, monkeypatch):
    from file_server import carrier_hotspots
    def unavailable(rows):
        raise ImportError("private-binary-body")
    monkeypatch.setattr(carrier_hotspots, "dbscan_labels", unavailable)
    with TestClient(app_for(source_rows(), tmp_path)) as client:
        response = client.post("/carrier-hotspots", json=scope().model_dump())
        assert response.status_code == 503 and "private-binary-body" not in response.text
