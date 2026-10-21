"""Monitoring endpoint shares confirmed geometry and computes baseline from that same area."""

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from file_server.api.area_queries import register_area_routes
from tests.file_server.test_monitoring_reports import source_rows, scope
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def test_endpoint_full_statistics_positive_page_and_reused_area(tmp_path):
    rows = source_rows() + [row("outside", x=114, day="2025-01-01"), row("old-outside", x=114, day="2024-12-01")]
    app = FastAPI()
    register_area_routes(app, observations=lambda _: rows, public_url=lambda _: "http://public",
                         storage_root=lambda: tmp_path, source="file_server")
    with TestClient(app) as client:
        query = scope(limit=1, polygon=SQUARE).model_dump()
        response = client.post("/vessel-monitoring-reports", json=query)
        assert response.status_code == 200
        result = response.json()
        assert result["statistics"]["detection_count"] == 5 and len(result["ships"]) == 1
        assert result["monthly_stats"][0]["previous_month"]["detection_count"] == 1
        second = client.post("/vessel-monitoring-reports", json={**query, "polygon": None,
            "area_id": result["area_id"], "offset": 1}).json()
        assert second["report_id"] == result["report_id"] and second["statistics"] == result["statistics"]
        assert second["ships"][0]["observation_id"] == "long"
        assert client.post("/vessel-monitoring-reports", json={}).status_code == 422
        assert client.post("/vessel-monitoring-reports", json={**query, "classification": "aircraft_carrier"}).status_code == 422
        drawing = client.post("/vessel-monitoring-reports", json={**query, "polygon": None, "area_name": "Hoàng Sa"}).json()
        assert drawing["status"] == "needs_drawing"
