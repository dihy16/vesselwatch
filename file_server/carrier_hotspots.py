"""Full-snapshot geographic DBSCAN and descriptive carrier-detection distributions."""

from collections import Counter, defaultdict
from datetime import date, timedelta
from hashlib import sha256
import json
from math import isfinite, radians
from statistics import fmean, median

from pydantic import Field

from .carrier_investigation import carrier_investigation_candidates
from .false_carriers import candidate_query
from .missed_carriers import CarrierReviewScope
from .spatial import UserPolygon, query_observations


EPS_KM = 30.0
MIN_SAMPLES = 2
EARTH_RADIUS_KM = 6371.0088
ALGORITHM = {"name": "DBSCAN", "eps_km": EPS_KM, "min_samples": MIN_SAMPLES,
             "metric": "haversine", "earth_radius_km": EARTH_RADIUS_KM}


class HotspotClusterScope(CarrierReviewScope):
    report_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    cluster_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class HotspotClusterRequest(HotspotClusterScope):
    polygon: UserPolygon | None = None


def dbscan_labels(rows):
    if not rows:
        return []
    from sklearn.cluster import DBSCAN
    coordinates = [[radians(row["position"]["latitude"]), radians(row["position"]["longitude"])]
                   for row in rows]
    return DBSCAN(eps=EPS_KM / EARTH_RADIUS_KM, min_samples=MIN_SAMPLES,
                  metric="haversine", algorithm="ball_tree").fit_predict(coordinates).tolist()


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


def build_hotspot_report(rows, scope, *, source_snapshot_id, geometry=None):
    query = candidate_query(scope)
    date_matches = query_observations(rows, query)
    selected = query_observations(date_matches, query, geometry)
    located = [row for row in selected if row["position"]["latitude"] is not None
               and row["position"]["longitude"] is not None]
    groups = defaultdict(list)
    noise = []
    for row, label in zip(located, dbscan_labels(located), strict=True):
        (noise if label == -1 else groups[label]).append(row)
    clusters, members = [], {}
    for group in groups.values():
        identity = sha256(json.dumps(sorted(row["observation_id"] for row in group)).encode()).hexdigest()[:32]
        members[identity] = group
        clusters.append({"cluster_id": identity, **distribution(group, scope)})
    clusters.sort(key=lambda item: (-item["detection_count"], item["cluster_id"]))
    for rank, cluster in enumerate(clusters, 1):
        cluster.update(rank=rank, name=f"Cụm {rank}")
    identity = {"source_snapshot_id": source_snapshot_id, "algorithm": ALGORITHM,
                "observed_from": scope.observed_from, "observed_to": scope.observed_to,
                "geometry": geometry.geometry if geometry else None}
    report_id = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return {"report_id": report_id, "source_snapshot_id": source_snapshot_id, "algorithm": ALGORITHM,
            "filters": query.model_dump(exclude={"polygon"}), "count_unit": "detections",
            "summary": distribution(selected, scope), "total_detections": len(selected),
            "located_count": len(located), "missing_position_count": len(selected) - len(located),
            "unlocated_in_date_range_count": sum(row["position"]["latitude"] is None
                                                or row["position"]["longitude"] is None for row in date_matches),
            "clustered_detection_count": len(located) - len(noise), "noise_count": len(noise),
            "total": len(clusters), "limit": scope.limit, "offset": scope.offset,
            "clusters": clusters[scope.offset:scope.offset + scope.limit],
            "next_offset": scope.offset + scope.limit if scope.offset + scope.limit < len(clusters) else None}, members


def hotspot_cluster_candidates(members, scope):
    # Reuse BR 17 ordering on exact membership; no bounding rectangle approximation.
    return carrier_investigation_candidates(members, scope)
