"""The real review endpoint shares polygon validation and full-source filtering."""

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from file_server.area_queries import register_area_routes
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def test_candidate_endpoint_date_area_scope_and_no_extra_score_or_dimension_gate(tmp_path):
    rows = [row("small", length=100, score=.5, day="2025-01-01"),
            row("missing", length=None, width=None, score=None, day="2025-12-31"),
            row("outside", day="2025-10-01", x=114),
            row("negative", label="not_aircraft_carrier", day="2025-10-01")]
    app = FastAPI()
    register_area_routes(app, observations=lambda _: rows, public_url=lambda _: "http://public",
                         storage_root=lambda: tmp_path, source="file_server")
    query = {"observed_from": "2025-01-01", "observed_to": "2025-12-31", "limit": 1}
    with TestClient(app) as client:
        result = client.post("/false-carrier-candidates", json=query).json()
        assert result["total"] == 3 and len(result["ships"]) == 1
        assert len(result["source_snapshot_id"]) == 64
        second = client.post("/false-carrier-candidates", json={**query, "offset": 1}).json()
        assert second["total"] == 3 and second["ships"][0]["observation_id"] == "outside"
        limited = client.post("/false-carrier-candidates", json={**query, "polygon": SQUARE}).json()
        assert limited["total"] == 2 and limited["filters"]["classification"] == "aircraft_carrier"
        drawing = client.post("/false-carrier-candidates", json={**query, "area_name": "Hoàng Sa"}).json()
        assert drawing["status"] == "needs_drawing" and "total" not in drawing
        assert client.post("/false-carrier-candidates", json={}).status_code == 422
        assert client.post("/false-carrier-candidates", json={**query, "min_length_m": 250}).status_code == 422


def test_investigation_ranks_full_scope_before_pagination_and_reuses_area_confirmation(tmp_path):
    rows = [row("large", 301, day="2025-01-01"), row("small", 299, day="2025-12-31"),
            row("edge", 300, day="2025-01-01"), row("missing", None, day="2025-01-01"),
            row("outside", 100, x=114, day="2025-01-01")]
    app = FastAPI()
    register_area_routes(app, observations=lambda _: rows, public_url=lambda _: "http://public",
                         storage_root=lambda: tmp_path, source="file_server")
    query = {"observed_from": "2025-01-01", "observed_to": "2025-12-31", "limit": 1, "polygon": SQUARE}
    with TestClient(app) as client:
        result = client.post("/carrier-investigation-candidates", json=query).json()
        assert result["total"] == 4 and result["dimension_candidate_count"] == 1
        assert result["visual_candidate_count"] == 3 and result["ships"][0]["observation_id"] == "small"
        second = client.post("/carrier-investigation-candidates", json={**query, "offset": 1}).json()
        assert second["ships"][0]["observation_id"] == "edge"
        reused = client.post("/carrier-investigation-candidates", json={**query, "polygon": None,
                                                                      "area_id": result["area_id"]}).json()
        assert reused["total"] == 4 and reused["source_snapshot_id"] == result["source_snapshot_id"]
        drawing = client.post("/carrier-investigation-candidates", json={**query, "polygon": None,
                                                                       "area_name": "Hoàng Sa"}).json()
        assert drawing["status"] == "needs_drawing"
        assert client.post("/carrier-investigation-candidates", json={}).status_code == 422
