"""Calendar coverage and full scoped totals stay separate from the review page."""

from copy import deepcopy
from datetime import date

import pytest

from file_server.monitoring_reports import MonitoringRequest, build_monitoring_report, month_windows
from file_server.spatial import AreaGeometry
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def source_rows():
    return [row("baseline", 310, day="2024-12-15"),
            row("short", 299, day="2025-01-01"),
            row("negative", 400, label="not_aircraft_carrier", score=.01, day="2025-01-20"),
            row("unknown", None, width=None, label="unknown", score=None, day="2025-01-22"),
            row("long", 300, day="2025-02-01"),
            row("negative-2", 350, label="not_aircraft_carrier", day="2025-02-15")]


def scope(**kwargs):
    return MonitoringRequest(observed_from="2025-01-01", observed_to="2025-02-28", **kwargs)


def report(rows=None, request=None, **kwargs):
    return build_monitoring_report(source_rows() if rows is None else rows, request or scope(),
                                   source_snapshot_id="a" * 64, **kwargs)


def test_all_three_labels_and_full_statistics_before_positive_review_pagination():
    result = report(request=scope(limit=1))
    stats = result["statistics"]
    assert stats["detection_count"] == 5
    assert stats["classification_counts"] == {"aircraft_carrier": 2, "not_aircraft_carrier": 2, "unknown": 1}
    assert result["total"] == 2 and result["dimension_candidate_count"] == 1 and result["visual_candidate_count"] == 1
    assert result["ships"][0]["observation_id"] == "short"
    assert result["statistics_filters"]["classification"] is None
    assert result["filters"]["classification"] == "aircraft_carrier"
    assert len(stats["daily_stats"]) == 59 and stats["daily_stats"][1]["count"] == 0
    assert stats["length_m"]["missing_count"] == 1
    assert stats["size_classification_counts"]["missing"]["unknown"] == 1
    later = report(request=scope(limit=1, offset=1))
    assert later["statistics"] == stats and later["monthly_stats"] == result["monthly_stats"]
    assert later["report_id"] == result["report_id"] and later["ships"][0]["observation_id"] == "long"


def test_calendar_months_compare_with_previous_full_month_not_rolling_30_days():
    jan, feb = report()["monthly_stats"]
    assert jan["queried_days"] == 31 and feb["queried_days"] == 28
    assert not jan["partial_month"] and not feb["partial_month"]
    assert jan["previous_month"]["month"] == "2024-12" and jan["previous_month"]["detection_count"] == 1
    assert jan["comparison"]["average_daily_change_pct"] == pytest.approx(200)
    assert feb["previous_month"]["month"] == "2025-01" and feb["previous_month"]["detection_count"] == 3
    assert feb["comparison"]["average_daily_change_pct"] == pytest.approx(100 * ((2 / 28) / (3 / 31) - 1))
    assert jan["comparison_by_classification"]["unknown"]["average_daily_change_pct"] is None


def test_partial_month_has_exact_dates_days_and_rate_not_full_month_label():
    result = report(request=MonitoringRequest(observed_from="2025-01-15", observed_to="2025-01-20"))
    month = result["monthly_stats"][0]
    assert month["partial_month"] and month["queried_days"] == 6
    assert month["observed_from"] == "2025-01-15" and month["observed_to"] == "2025-01-20"
    assert month["detection_count"] == 1 and month["average_daily_count"] == 1 / 6
    assert month["previous_month"]["observed_from"] == "2024-12-01"
    assert month["previous_month"]["observed_to"] == "2024-12-31"
    assert result["total"] == 0  # Baseline positives are not reviewed outside the requested period.


def test_zero_baseline_and_empty_calendar_months_never_produce_infinite_percent():
    request = MonitoringRequest(observed_from="2025-01-01", observed_to="2025-03-31")
    rows = [row("current", day="2025-03-01")]
    result = report(rows, request)
    assert [item["detection_count"] for item in result["monthly_stats"]] == [0, 0, 1]
    for item in result["monthly_stats"]:
        assert item["comparison"]["direction"] == "no_baseline"
        assert item["comparison"]["average_daily_change_pct"] is None


def test_leap_year_and_year_boundary_windows():
    windows = list(month_windows(date(2023, 12, 31), date(2024, 3, 1)))
    assert windows[0] == (date(2023, 12, 31), date(2023, 12, 31), date(2023, 11, 1), date(2023, 11, 30))
    assert windows[2] == (date(2024, 2, 1), date(2024, 2, 29), date(2024, 1, 1), date(2024, 1, 31))
    result = report([], MonitoringRequest(observed_from="2024-02-01", observed_to="2024-02-29"))
    assert result["monthly_stats"][0]["queried_days"] == 29


def test_same_area_filters_current_and_baseline_and_reports_unlocated_before_area():
    rows = source_rows() + [row("baseline-outside", day="2024-12-20", x=114),
                            row("outside", day="2025-01-01", x=114),
                            row("unlocated", day="2025-01-01", x=None, y=None)]
    result = report(rows, scope(polygon=SQUARE), geometry=AreaGeometry(SQUARE))
    assert result["statistics"]["detection_count"] == 5
    assert result["monthly_stats"][0]["previous_month"]["detection_count"] == 1
    assert result["unlocated_in_date_range_count"] == 1 and result["missing_position_count"] == 0


def test_snapshot_binding_dedup_and_inputs_unchanged():
    rows = source_rows()
    rows.append(deepcopy(rows[1]))
    before = deepcopy(rows)
    result = report(rows)
    assert rows == before and result["statistics"]["detection_count"] == 5
    changed = build_monitoring_report(rows, scope(), source_snapshot_id="b" * 64)
    assert changed["report_id"] != result["report_id"]


def test_report_can_have_only_noncarrier_and_unknown_labels_without_review_candidates():
    rows = [row("negative", label="not_aircraft_carrier", day="2025-01-01"),
            row("unknown", label="unknown", score=None, day="2025-01-01")]
    result = report(rows)
    assert result["statistics"]["detection_count"] == 2 and result["total"] == 0 and result["ships"] == []


def test_no_underflow_when_previous_calendar_month_cannot_exist():
    with pytest.raises(ValueError, match="tháng dương lịch liền trước"):
        MonitoringRequest(observed_from="0001-01-01", observed_to="0001-01-02")
