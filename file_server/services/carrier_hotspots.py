"""Full-snapshot geographic DBSCAN and descriptive carrier-detection distributions."""

from collections import defaultdict
from hashlib import sha256
import json
from math import radians

from file_server.services.carrier_investigation import carrier_investigation_candidates
from file_server.services.distributions import distribution
from file_server.services.false_carriers import candidate_query
from file_server.services.spatial import query_observations


EPS_KM = 30.0
MIN_SAMPLES = 2
EARTH_RADIUS_KM = 6371.0088
ALGORITHM = {"name": "DBSCAN", "eps_km": EPS_KM, "min_samples": MIN_SAMPLES,
             "metric": "haversine", "earth_radius_km": EARTH_RADIUS_KM}


def dbscan_labels(rows):
    if not rows:
        return []
    from sklearn.cluster import DBSCAN
    coordinates = [[radians(row["position"]["latitude"]), radians(row["position"]["longitude"])]
                   for row in rows]
    return DBSCAN(eps=EPS_KM / EARTH_RADIUS_KM, min_samples=MIN_SAMPLES,
                  metric="haversine", algorithm="ball_tree").fit_predict(coordinates).tolist()


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
