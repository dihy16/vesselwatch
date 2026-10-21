"""Hotspot summaries preserve complete counts and detailed review cannot switch clusters."""

from copy import deepcopy
import json

import httpx
import pytest

from ship_agent.hotspot_client import request_carrier_hotspots, request_carrier_hotspot_candidates
from tests.file_server.test_carrier_hotspots import report, source_rows, scope, stub_labels
from tests.integration.test_carrier_investigation_client import investigation_payload


def payload():
    data, _ = report(source_rows())
    return {"status": "complete", "area_id": "a" * 32, "map_url": "http://public/map", **data}


def test_summary_endpoint_counts_daily_zeros_and_missing_fields():
    def respond(request):
        assert request.url.path == "/carrier-hotspots" and json.loads(request.content) == scope().model_dump()
        return httpx.Response(200, json=payload())
    result = request_carrier_hotspots(scope().model_dump(), transport=httpx.MockTransport(respond))
    assert result["total"] == 2 and result["summary"]["carrier_score"]["count"] == 6
    assert result["summary"]["carrier_score"]["missing_count"] == 1


@pytest.mark.parametrize("failure", ["source", "algorithm", "date-filter", "count", "missing-page", "rank", "duplicate",
                                    "daily", "measurement", "histogram", "extent", "timestamp", "continuation"])
def test_inconsistent_or_mixed_report_is_rejected(failure):
    result = payload()
    if failure == "source":
        result.pop("source_snapshot_id")
    elif failure == "algorithm":
        result["algorithm"] = {**result["algorithm"], "eps_km": 20}
    elif failure == "date-filter":
        result["filters"]["observed_from"] = "2024-01-01"
    elif failure == "count":
        result["noise_count"] += 1
    elif failure == "missing-page":
        result["clusters"].pop()
    elif failure == "rank":
        result["clusters"][0]["rank"] = 2
    elif failure == "duplicate":
        result["clusters"][1]["cluster_id"] = result["clusters"][0]["cluster_id"]
    elif failure == "daily":
        result["clusters"][0]["daily_stats"][0]["count"] += 1
    elif failure == "measurement":
        result["summary"]["length_m"]["missing_count"] += 1
    elif failure == "histogram":
        result["summary"]["carrier_score"]["histogram"][0]["count"] += 1
    elif failure == "extent":
        result["clusters"][0]["geographic_extent"]["north"] = 100
    elif failure == "timestamp":
        result["summary"]["first_observed_at"] = "2025-01-01T00:00:00+07:00"
    else:
        result["next_offset"] = 1
    with pytest.raises(ValueError):
        request_carrier_hotspots(scope().model_dump(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result)))


def test_cluster_pagination_retains_global_summary_and_ids():
    data, _ = report(source_rows(), limit=1, offset=1)
    result = request_carrier_hotspots(scope(limit=1, offset=1).model_dump(), transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"status": "complete", "area_id": "a" * 32,
                                           "map_url": "http://public/map", **data})))
    assert result["clusters"][0]["rank"] == 2 and result["total_detections"] == 7


def test_review_is_bound_to_both_report_and_membership():
    query = {**scope().model_dump(), "report_id": "b" * 64, "cluster_id": "c" * 32}
    data = {**investigation_payload(), "report_id": query["report_id"], "cluster_id": query["cluster_id"]}
    def respond(request):
        assert request.url.path == "/carrier-hotspot-candidates"
        return httpx.Response(200, json=data)
    assert request_carrier_hotspot_candidates(query, transport=httpx.MockTransport(respond))["total"] == 1
    for key in ("report_id", "cluster_id"):
        wrong = deepcopy(data)
        wrong[key] = "d" * len(wrong[key])
        with pytest.raises(ValueError):
            request_carrier_hotspot_candidates(query, transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=wrong)))
