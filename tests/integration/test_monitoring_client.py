"""Report transport rejects changed scope, incomplete month coverage and invented comparisons."""

from copy import deepcopy
import json

import httpx
import pytest

from file_server.monitoring_reports import LABELS, build_monitoring_report, compare_rates
from ship_agent.monitoring_client import request_monitoring_report
from tests.file_server.test_monitoring_reports import scope
from tests.integration.test_false_carrier_client import positive_payload


def payload():
    base = positive_payload()["ships"][0]
    rows = []
    for identity, day, label, length in (("baseline", "2024-12-15", "aircraft_carrier", 310),
            ("short", "2025-01-01", "aircraft_carrier", 100), ("long", "2025-02-01", "aircraft_carrier", 300),
            ("negative", "2025-01-20", "not_aircraft_carrier", 400), ("unknown", "2025-02-15", "unknown", None)):
        row = deepcopy(base)
        row.update(observation_id=identity, observed_date=day, observed_at=day + "T00:00:00+00:00",
                   classification=label, length_m=length)
        rows.append(row)
    data = build_monitoring_report(rows, scope(), source_snapshot_id="a" * 64)
    return {"status": "complete", "area_id": "b" * 32, "map_url": "http://public/map", "area_name": "Vùng tùy ý", **data}


def test_endpoint_and_full_report_plus_validated_positive_page():
    def respond(request):
        assert request.url.path == "/vessel-monitoring-reports" and json.loads(request.content) == scope().model_dump()
        return httpx.Response(200, json=payload())
    result = request_monitoring_report(scope().model_dump(), transport=httpx.MockTransport(respond))
    assert result["statistics"]["detection_count"] == 4 and result["total"] == 2


@pytest.mark.parametrize("failure", ["snapshot", "policy", "scope", "classifications", "daily", "size-matrix",
    "review-total", "missing-month", "partial-days", "baseline-range", "rate", "percent", "class-percent", "month-vs-day"])
def test_bad_report_never_reaches_model_or_artifact(failure):
    result = payload()
    if failure == "snapshot":
        result.pop("source_snapshot_id")
    elif failure == "policy":
        result["comparison_policy"] = "rolling_30_days"
    elif failure == "scope":
        result["statistics_filters"]["observed_from"] = "2024-01-01"
    elif failure == "classifications":
        result["statistics"]["classification_counts"]["unknown"] += 1
    elif failure == "daily":
        result["statistics"]["daily_stats"][0]["classification_counts"]["unknown"] += 1
    elif failure == "size-matrix":
        result["statistics"]["size_classification_counts"]["below_300m"]["aircraft_carrier"] += 1
    elif failure == "review-total":
        result["total"] += 1
    elif failure == "missing-month":
        result["monthly_stats"].pop()
    elif failure == "partial-days":
        result["monthly_stats"][0]["queried_days"] = 30
    elif failure == "baseline-range":
        result["monthly_stats"][0]["previous_month"]["observed_to"] = "2024-12-30"
    elif failure == "rate":
        result["monthly_stats"][0]["average_daily_count"] = 100
    elif failure == "percent":
        result["monthly_stats"][0]["comparison"]["average_daily_change_pct"] = 10000
    elif failure == "class-percent":
        result["monthly_stats"][0]["comparison_by_classification"]["unknown"]["average_daily_change_pct"] = 0
    else:
        jan, feb = result["monthly_stats"]
        jan["classification_counts"], feb["classification_counts"] = feb["classification_counts"], jan["classification_counts"]
        for month in (jan, feb):
            previous = month["previous_month"]
            month["comparison_by_classification"] = {
                label: compare_rates(month["classification_counts"][label], month["queried_days"],
                    previous["classification_counts"][label], previous["queried_days"]) for label in LABELS}
    with pytest.raises(ValueError):
        request_monitoring_report(scope().model_dump(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result)))
