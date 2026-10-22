"""Descriptive numeric, geographic and daily observation distributions."""

from collections import Counter
from datetime import date, timedelta
from math import isfinite
from statistics import fmean, median


def _number(value):
    return type(value) in (int, float) and isfinite(value)

def numeric_summary(rows, key):
    values = [row[key] for row in rows if _number(row.get(key))]
    return {"count": len(values), "missing_count": len(rows) - len(values),
            "min": min(values) if values else None, "max": max(values) if values else None,
            "mean": fmean(values) if values else None, "median": median(values) if values else None}

def geographic_extent(rows):
    if not rows:
        return None
    latitudes = [row["position"]["latitude"] for row in rows]
    longitudes = sorted(row["position"]["longitude"] % 360 for row in rows)
    # Use the shortest longitude arc, including groups straddling the date line.
    gap = max(range(len(longitudes)), key=lambda i:
              (longitudes[(i + 1) % len(longitudes)] - longitudes[i]) % 360
              if len(longitudes) > 1 else 360)
    west = (longitudes[(gap + 1) % len(longitudes)] + 180) % 360 - 180
    east = (longitudes[gap] + 180) % 360 - 180
    return {"south": min(latitudes), "north": max(latitudes), "west": west, "east": east,
            "crosses_antimeridian": west > east}

def distribution(rows, scope):
    counts = Counter(row["observed_date"] for row in rows)
    first, last = date.fromisoformat(scope.observed_from), date.fromisoformat(scope.observed_to)
    daily = [{"date": (first + timedelta(days=index)).isoformat(),
              "count": counts[(first + timedelta(days=index)).isoformat()]}
             for index in range((last - first).days + 1)]
    located = [row for row in rows if row["position"]["latitude"] is not None
               and row["position"]["longitude"] is not None]
    known_lengths = [row["length_m"] for row in rows if _number(row.get("length_m"))]
    scores = [row["confidence"] for row in rows if _number(row.get("confidence"))]
    histogram = [{"lower": index / 10, "upper": (index + 1) / 10,
                  "upper_inclusive": index == 9,
                  "count": sum(index / 10 <= score < (index + 1) / 10
                               or (index == 9 and score == 1) for score in scores)}
                 for index in range(10)]
    return {"detection_count": len(rows), "active_day_count": len(counts), "daily_stats": daily,
            "first_observed_at": min((row["observed_at"] for row in rows), default=None),
            "last_observed_at": max((row["observed_at"] for row in rows), default=None),
            "geographic_extent": geographic_extent(located),
            "length_m": numeric_summary(rows, "length_m"), "width_m": numeric_summary(rows, "width_m"),
            "length_groups": {"below_300m": sum(length < 300 for length in known_lengths),
                              "at_least_300m": sum(length >= 300 for length in known_lengths),
                              "missing": len(rows) - len(known_lengths)},
            "carrier_score": {**numeric_summary(rows, "confidence"), "histogram": histogram}}
