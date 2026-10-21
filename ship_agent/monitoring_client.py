"""Validate report totals, calendar coverage and the matching detailed-review page."""

from datetime import date
from math import isclose
import re

from file_server.monitoring_reports import LABELS, COMPARISON_POLICY, month_windows, compare_rates
from .area_client import _request_review_candidates, _validate_investigation_groups
from .hotspot_client import _count, _distribution


def _labels(counts, total):
    if set(counts) != set(LABELS) or sum(_count(counts[label]) for label in LABELS) != total:
        raise ValueError("Invalid monitoring classification totals.")


def _period(item, first, last):
    total = _count(item["detection_count"])
    days = (last - first).days + 1
    from calendar import monthrange
    calendar_days = monthrange(first.year, first.month)[1]
    if (item["month"] != first.isoformat()[:7] or item["observed_from"] != first.isoformat()
            or item["observed_to"] != last.isoformat() or item["queried_days"] != days
            or item["calendar_days"] != calendar_days
            or item["partial_month"] is not (first.day != 1 or last.day != calendar_days)
            or not isclose(item["average_daily_count"], total / days, rel_tol=1e-12)
            or not 0 <= _count(item["active_day_count"]) <= min(days, total)):
        raise ValueError("Invalid monitoring calendar-month coverage.")
    _labels(item["classification_counts"], total)


def _comparison(item, expected):
    if set(item) != set(expected):
        raise ValueError("Invalid monitoring comparison fields.")
    for key, value in expected.items():
        if isinstance(value, (int, float)):
            if type(item[key]) not in (int, float) or not isclose(item[key], value, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Incorrect monitoring monthly comparison.")
        elif item[key] != value:
            raise ValueError("Incorrect monitoring comparison status.")


def request_monitoring_report(query, *, transport=None):
    result = _request_review_candidates(query, endpoint="vessel-monitoring-reports", transport=transport,
                                        matches=lambda row: row["classification"] == "aircraft_carrier")
    if result["status"] != "complete":
        return result
    _validate_investigation_groups(result)
    try:
        if (result["report_kind"] != "vessel_monitoring" or result["comparison_policy"] != COMPARISON_POLICY
                or not isinstance(result["report_id"], str) or not re.fullmatch(r"[a-f0-9]{64}", result["report_id"])
                or result["statistics_filters"]["classification"] is not None
                or any(result["statistics_filters"][key] != query[key] for key in ("observed_from", "observed_to"))):
            raise ValueError("Wrong monitoring report scope or identity.")
        stats = result["statistics"]
        _distribution(stats, query)
        _labels(stats["classification_counts"], stats["detection_count"])
        if stats["classification_counts"]["aircraft_carrier"] != result["total"]:
            raise ValueError("Review candidates do not match the report's carrier-positive count.")
        for entry in stats["daily_stats"]:
            _labels(entry["classification_counts"], entry["count"])
        for label in LABELS:
            if sum(entry["classification_counts"][label] for entry in stats["daily_stats"]) != stats["classification_counts"][label]:
                raise ValueError("Daily monitoring classifications do not reconcile.")
        groups = stats["size_classification_counts"]
        for group in ("below_300m", "at_least_300m", "missing"):
            _labels(groups[group], stats["length_groups"][group])
        if any(sum(groups[group][label] for group in groups) != stats["classification_counts"][label] for label in LABELS):
            raise ValueError("Monitoring size/classification matrix does not reconcile.")
        first, last = date.fromisoformat(query["observed_from"]), date.fromisoformat(query["observed_to"])
        windows = list(month_windows(first, last))
        if len(result["monthly_stats"]) != len(windows):
            raise ValueError("Incomplete calendar-month report.")
        for item, (start, end, previous_start, previous_end) in zip(result["monthly_stats"], windows, strict=True):
            _period(item, start, end)
            days = [entry for entry in stats["daily_stats"] if start.isoformat() <= entry["date"] <= end.isoformat()]
            if (sum(entry["count"] for entry in days) != item["detection_count"]
                    or sum(entry["count"] > 0 for entry in days) != item["active_day_count"]
                    or any(sum(entry["classification_counts"][label] for entry in days)
                           != item["classification_counts"][label] for label in LABELS)):
                raise ValueError("Monthly monitoring statistics do not match daily observations.")
            previous = item["previous_month"]
            _period(previous, previous_start, previous_end)
            _comparison(item["comparison"], compare_rates(item["detection_count"], item["queried_days"],
                         previous["detection_count"], previous["queried_days"]))
            for label in LABELS:
                _comparison(item["comparison_by_classification"][label], compare_rates(item["classification_counts"][label],
                    item["queried_days"], previous["classification_counts"][label], previous["queried_days"]))
        if (sum(item["detection_count"] for item in result["monthly_stats"]) != stats["detection_count"]
                or any(sum(item["classification_counts"][label] for item in result["monthly_stats"])
                       != stats["classification_counts"][label] for label in LABELS)
                or not 0 <= _count(result["missing_position_count"]) <= stats["detection_count"]
                or _count(result["unlocated_in_date_range_count"]) < result["missing_position_count"]):
            raise ValueError("Monitoring coverage or monthly totals do not reconcile.")
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Invalid monitoring report response.") from exc
    return result
