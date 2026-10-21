"""Order the complete carrier-positive scope before paginating BR 17 work."""

from math import isfinite

from .false_carriers import candidate_query
from .spatial import query_observations


LENGTH_THRESHOLD_M = 300


def dimension_priority(row):
    length = row.get("length_m")
    return type(length) in (int, float) and isfinite(length) and 0 < length < LENGTH_THRESHOLD_M


def carrier_investigation_candidates(rows, scope, geometry=None):
    query = candidate_query(scope)
    matches = query_observations(rows, query, geometry)
    # query_observations already provides stable time/ID order within each group.
    short = [row for row in matches if dimension_priority(row)]
    remaining = [row for row in matches if not dimension_priority(row)]
    ordered = short + remaining
    return {"filters": query.model_dump(exclude={"polygon"}), "count_unit": "detections",
            "total": len(ordered), "dimension_candidate_count": len(short),
            "visual_candidate_count": len(remaining), "length_threshold_m": LENGTH_THRESHOLD_M,
            "limit": scope.limit, "offset": scope.offset,
            "ships": ordered[scope.offset:scope.offset + scope.limit]}
