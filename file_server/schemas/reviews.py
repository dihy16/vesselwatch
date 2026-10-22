"""Date-required review scopes and hotspot membership requests."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from file_server.schemas.area_models import AreaRequest
from file_server.schemas.geometry import UserPolygon


class CarrierReviewScope(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    observed_from: str = Field(description="Ngày đầu YYYY-MM-DD, bắt buộc.")
    observed_to: str = Field(description="Ngày cuối YYYY-MM-DD, bắt buộc, gồm cả hai đầu mốc.")
    area_name: str | None = Field(default=None, max_length=160)
    area_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    center_latitude: float | None = Field(default=None, gt=-90, lt=90)
    center_longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_nm: float | None = Field(default=None, gt=0,
        description="Mở rộng mỗi hướng từ tâm căn cứ hoặc tọa độ, hải lý; ô vuông cạnh khoảng 2 lần giá trị này.")
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_scope(self):
        AreaRequest(observed_from=self.observed_from, observed_to=self.observed_to,
                    area_name=self.area_name, area_id=self.area_id,
                    center_latitude=self.center_latitude, center_longitude=self.center_longitude, radius_nm=self.radius_nm,
                    polygon=getattr(self, "polygon", None), limit=self.limit, offset=self.offset)
        return self

class MissedCarrierScope(CarrierReviewScope):
    """Date/area scope for the fixed missed-carrier score and size gates."""

class MissedCarrierRequest(MissedCarrierScope):
    polygon: UserPolygon | None = None

class FalseCarrierScope(CarrierReviewScope):
    """All saved carrier positives, without an extra score or dimension gate."""

class FalseCarrierRequest(FalseCarrierScope):
    polygon: UserPolygon | None = None

class HotspotClusterScope(CarrierReviewScope):
    report_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    cluster_id: str = Field(pattern=r"^[a-f0-9]{32}$")

class HotspotClusterRequest(HotspotClusterScope):
    polygon: UserPolygon | None = None
