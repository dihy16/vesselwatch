"""Scoped monitoring counts and calendar-month comparisons from one source snapshot."""

from calendar import monthrange
from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
import json

from pydantic import model_validator

from .area_models import AreaQueryInput, AreaRequest
from .carrier_hotspots import distribution
from .carrier_investigation import carrier_investigation_candidates
from .missed_carriers import CarrierReviewScope
from .spatial import UserPolygon, query_observations


LABELS = ("aircraft_carrier", "not_aircraft_carrier", "unknown")
COMPARISON_POLICY = "calendar_month_vs_previous_calendar_month_daily_rate"


class MonitoringScope(CarrierReviewScope):
    """limit/offset select the detailed-review page, never truncate statistics."""

    @model_validator(mode="after")
    def previous_month_exists(self):
        if self.observed_from.startswith("0001-01"):
            raise ValueError("Khoảng báo cáo cần có tháng dương lịch liền trước để đối chiếu.")
        return self


class MonitoringRequest(MonitoringScope):
    polygon: UserPolygon | None = None


def monitoring_query(scope):
    return AreaRequest(observed_from=scope.observed_from, observed_to=scope.observed_to,
                       area_name=scope.area_name, area_id=scope.area_id,
                       polygon=getattr(scope, "polygon", None), limit=scope.limit, offset=scope.offset)


def classification_counts(rows):
    counts = Counter(row["classification"] for row in rows)
    return {label: counts[label] for label in LABELS}


def month_windows(first, last):
    cursor = first.replace(day=1)
    while cursor <= last:
        end = cursor.replace(day=monthrange(cursor.year, cursor.month)[1])
        previous_end = cursor - timedelta(days=1)
        yield max(first, cursor), min(last, end), previous_end.replace(day=1), previous_end
        if end >= last:
            break
        cursor = end + timedelta(days=1)


def _period(rows, first, last):
    days = (last - first).days + 1
    return {"month": first.isoformat()[:7], "observed_from": first.isoformat(),
            "observed_to": last.isoformat(), "queried_days": days,
            "calendar_days": monthrange(first.year, first.month)[1],
            "partial_month": first.day != 1 or last.day != monthrange(first.year, first.month)[1],
            "detection_count": len(rows), "average_daily_count": len(rows) / days,
            "classification_counts": classification_counts(rows),
            "active_day_count": len({row["observed_date"] for row in rows})}


def compare_rates(current_count, current_days, previous_count, previous_days):
    current, previous = current_count / current_days, previous_count / previous_days
    return {"count_delta": current_count - previous_count, "average_daily_delta": current - previous,
            "average_daily_change_pct": 100 * (current - previous) / previous if previous_count else None,
            "direction": ("no_baseline" if not previous_count else "increase" if current > previous
                          else "decrease" if current < previous else "unchanged")}


def build_monitoring_report(rows, scope, *, source_snapshot_id, geometry=None):
    query = monitoring_query(scope)
    selected = query_observations(rows, query, geometry)
    statistics = {**distribution(selected, scope), "classification_counts": classification_counts(selected)}
    by_day = {}
    for row in selected:
        by_day.setdefault(row["observed_date"], []).append(row)
    for entry in statistics["daily_stats"]:
        entry["classification_counts"] = classification_counts(by_day.get(entry["date"], []))
    statistics["size_classification_counts"] = {
        group: classification_counts([row for row in selected if
            (row["length_m"] is None if group == "missing" else
             row["length_m"] is not None and (row["length_m"] < 300 if group == "below_300m" else row["length_m"] >= 300))])
        for group in ("below_300m", "at_least_300m", "missing")}
    first, last = date.fromisoformat(scope.observed_from), date.fromisoformat(scope.observed_to)
    monthly = []
    for start, end, previous_start, previous_end in month_windows(first, last):
        current_rows = [row for row in selected if start.isoformat() <= row["observed_date"] <= end.isoformat()]
        previous_rows = query_observations(rows, AreaQueryInput(observed_from=previous_start.isoformat(),
                                           observed_to=previous_end.isoformat()), geometry)
        current, previous = _period(current_rows, start, end), _period(previous_rows, previous_start, previous_end)
        comparison = compare_rates(current["detection_count"], current["queried_days"],
                                   previous["detection_count"], previous["queried_days"])
        monthly.append({**current, "previous_month": previous, "comparison": comparison,
                        "comparison_by_classification": {
                            label: compare_rates(current["classification_counts"][label], current["queried_days"],
                                                 previous["classification_counts"][label], previous["queried_days"])
                            for label in LABELS}})
    identity = {"source_snapshot_id": source_snapshot_id, "observed_from": scope.observed_from,
                "observed_to": scope.observed_to, "geometry": geometry.geometry if geometry else None,
                "comparison_policy": COMPARISON_POLICY, "review_policy": "br17_length_lt_300m_then_reference_review"}
    date_rows = query_observations(rows, AreaQueryInput(observed_from=scope.observed_from, observed_to=scope.observed_to))
    return {"report_id": sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
            "report_kind": "vessel_monitoring", "source_snapshot_id": source_snapshot_id,
            "statistics_filters": query.model_dump(exclude={"polygon"}),
            "statistics": statistics, "monthly_stats": monthly, "comparison_policy": COMPARISON_POLICY,
            "unlocated_in_date_range_count": sum(row["position"]["latitude"] is None for row in date_rows),
            "missing_position_count": sum(row["position"]["latitude"] is None for row in selected),
            **carrier_investigation_candidates(selected, scope)}
