"""Inclusive, date-required screening for potential missed-carrier observations."""

from file_server.schemas.area_models import AreaRequest
from file_server.schemas.reviews import MissedCarrierScope
from file_server.services.spatial import query_observations


def candidate_query(scope: MissedCarrierScope) -> AreaRequest:
    return AreaRequest(observed_from=scope.observed_from, observed_to=scope.observed_to,
                       area_name=scope.area_name, area_id=scope.area_id,
                       center_latitude=scope.center_latitude, center_longitude=scope.center_longitude, radius_nm=scope.radius_nm,
                       polygon=getattr(scope, "polygon", None), classification="not_aircraft_carrier",
                       min_length_m=250, limit=scope.limit, offset=scope.offset)


def missed_carrier_candidates(rows, scope: MissedCarrierScope, geometry=None):
    query = candidate_query(scope)
    matches = [row for row in query_observations(rows, query, geometry)
               if row["confidence"] is not None and row["confidence"] <= .01]
    return {"filters": {**query.model_dump(exclude={"polygon"}), "carrier_score_lte": .01},
            "count_unit": "detections", "total": len(matches), "limit": scope.limit,
            "offset": scope.offset, "ships": matches[scope.offset:scope.offset + scope.limit]}
