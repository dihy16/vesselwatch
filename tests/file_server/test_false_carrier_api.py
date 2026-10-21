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
