"""BR 19 shares confirmed area rules and filters/sorts the entire scope before paging."""

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from file_server.api.area_queries import register_area_routes
from tests.file_server.test_label_review_candidates import source_rows, scope
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def test_endpoint_global_score_order_full_statistics_and_confirmed_area_reuse(tmp_path):
    rows = source_rows() + [row("outside", x=114, score=.001, day="2025-01-01")]
    app = FastAPI()
    register_area_routes(app, observations=lambda _: rows, public_url=lambda _: "http://public",
                         storage_root=lambda: tmp_path, source="file_server")
    with TestClient(app) as client:
        query = scope(limit=1, polygon=SQUARE).model_dump()
        result = client.post("/carrier-label-review-candidates", json=query).json()
        assert result["total"] == 5 and result["ships"][0]["observation_id"] == "stored-positive"
        assert result["candidate_statistics"]["detection_count"] == 5
        second = client.post("/carrier-label-review-candidates", json={**query, "polygon": None,
            "area_id": result["area_id"], "offset": 1}).json()
        assert second["ships"][0]["observation_id"] == "low"
        assert second["source_snapshot_id"] == result["source_snapshot_id"]
        assert second["candidate_statistics"] == result["candidate_statistics"]
        high = client.post("/carrier-label-review-candidates", json={**query, "offset": 3}).json()
        assert high["ships"][0]["confidence"] == 1
        assert client.post("/carrier-label-review-candidates", json={}).status_code == 422
        for extra in ({"min_length_m": 300}, {"max_score": .9}, {"classification": "unknown"}):
            assert client.post("/carrier-label-review-candidates", json={**query, **extra}).status_code == 422
        waiting = client.post("/carrier-label-review-candidates", json={**query, "polygon": None, "area_name": "Hoàng Sa"}).json()
        assert waiting["status"] == "needs_drawing"
