"""Date-required screening of saved positives for possible non-carrier evidence."""

from file_server.schemas.area_models import AreaRequest
from file_server.schemas.reviews import FalseCarrierScope
from file_server.services.spatial import query_observations


def candidate_query(scope: FalseCarrierScope) -> AreaRequest:
    return AreaRequest(observed_from=scope.observed_from, observed_to=scope.observed_to,
                       area_name=scope.area_name, area_id=scope.area_id,
                       polygon=getattr(scope, "polygon", None), classification="aircraft_carrier",
                       limit=scope.limit, offset=scope.offset)


def false_carrier_candidates(rows, scope: FalseCarrierScope, geometry=None):
    query = candidate_query(scope)
    matches = query_observations(rows, query, geometry)
    return {"filters": query.model_dump(exclude={"polygon"}), "count_unit": "detections",
            "total": len(matches), "limit": scope.limit, "offset": scope.offset,
            "ships": matches[scope.offset:scope.offset + scope.limit]}
