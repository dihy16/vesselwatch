"""Inclusive, date-required screening for potential missed-carrier observations."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .area_models import AreaRequest
from .spatial import UserPolygon, query_observations


class CarrierReviewScope(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    observed_from: str = Field(description="Ngày đầu YYYY-MM-DD, bắt buộc.")
    observed_to: str = Field(description="Ngày cuối YYYY-MM-DD, bắt buộc, gồm cả hai đầu mốc.")
    area_name: str | None = Field(default=None, max_length=160)
    area_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_scope(self):
        AreaRequest(observed_from=self.observed_from, observed_to=self.observed_to,
                    area_name=self.area_name, area_id=self.area_id,
                    polygon=getattr(self, "polygon", None), limit=self.limit, offset=self.offset)
        return self


class MissedCarrierScope(CarrierReviewScope):
    """Date/area scope for the fixed missed-carrier score and size gates."""


class MissedCarrierRequest(MissedCarrierScope):
    polygon: UserPolygon | None = None


def candidate_query(scope: MissedCarrierScope) -> AreaRequest:
    return AreaRequest(observed_from=scope.observed_from, observed_to=scope.observed_to,
                       area_name=scope.area_name, area_id=scope.area_id,
                       polygon=getattr(scope, "polygon", None), classification="not_aircraft_carrier",
                       min_length_m=250, limit=scope.limit, offset=scope.offset)


def missed_carrier_candidates(rows, scope: MissedCarrierScope, geometry=None):
    query = candidate_query(scope)
    matches = [row for row in query_observations(rows, query, geometry)
               if row["confidence"] is not None and row["confidence"] <= .01]
    return {"filters": {**query.model_dump(exclude={"polygon"}), "carrier_score_lte": .01},
            "count_unit": "detections", "total": len(matches), "limit": scope.limit,
            "offset": scope.offset, "ships": matches[scope.offset:scope.offset + scope.limit]}
