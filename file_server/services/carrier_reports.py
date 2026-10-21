"""Count model-positive observations and render daily PNG reports in memory."""

from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
import json
from typing import Iterable


MAX_REPORT_DAYS = 366


def daily_carrier_report(
    observations: Iterable[dict], observed_from: date, observed_to: date,
) -> dict:
    """Count separate observation IDs, using the already parsed caption date."""
    days = (observed_to - observed_from).days + 1
    if not 1 <= days <= MAX_REPORT_DAYS:
        raise ValueError("Khoảng ngày phải có từ 1 đến 366 ngày, gồm cả hai đầu mốc.")
    counts = Counter()
    seen = set()
    for observation in observations:
        day = date.fromisoformat(observation["observed_date"])
        if not observed_from <= day <= observed_to:
            continue
        identity = observation["observation_id"]
        if identity in seen:
            continue
        seen.add(identity)
        if observation["classification"] == "aircraft_carrier":
            counts[day.isoformat()] += 1
    daily_stats = [
        {"date": (observed_from + timedelta(days=offset)).isoformat(),
         "possible_aircraft_carrier_count": counts[
             (observed_from + timedelta(days=offset)).isoformat()
         ]}
        for offset in range(days)
    ]
    report = {
        "observed_from": observed_from.isoformat(),
        "observed_to": observed_to.isoformat(),
        "timezone": "UTC",
        "count_unit": "detections",
        "classification": "aircraft_carrier",
        "total_detections": sum(counts.values()),
        "daily_stats": daily_stats,
    }
    # Bind the chart URL to these exact dates/counts, even after a server restart.
    report["report_id"] = sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report
