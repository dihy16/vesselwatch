"""BR 19 reviews every saved positive, ordering lower scores before higher scores."""

from .carrier_hotspots import distribution
from .false_carriers import candidate_query
from .spatial import query_observations


REVIEW_ORDER = "carrier_score_ascending_missing_last_then_time_id"


def review_order(row):
    score = row["confidence"]
    return (score is None, score if score is not None else 0,
            row["observed_at"], row["observation_id"])


def label_review_candidates(rows, scope, geometry=None):
    query = candidate_query(scope)
    matches = query_observations(rows, query, geometry)
    matches.sort(key=review_order)
    return {"filters": query.model_dump(exclude={"polygon"}), "count_unit": "detections",
            "total": len(matches), "limit": scope.limit, "offset": scope.offset,
            "review_order": REVIEW_ORDER, "candidate_statistics": distribution(matches, scope),
            "ships": matches[scope.offset:scope.offset + scope.limit]}
