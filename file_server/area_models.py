"""Validated area-query arguments shared by the agent and data API."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .spatial import UserPolygon


class AreaQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    area_name: str | None = Field(default=None, max_length=160)
    area_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    observed_from: str | None = None
    observed_to: str | None = None
    classification: Literal["aircraft_carrier", "not_aircraft_carrier", "unknown"] | None = None
    ship_id: str | None = None
    length_gt_m: float | None = Field(default=None, ge=0)
    carrier_score_gt: float | None = Field(default=None, ge=0, le=1,
        description="Carrier score lớn hơn nghiêm ngặt mức này; trên 80% dùng 0.8.")
    min_length_m: float | None = Field(default=None, ge=0)
    max_length_m: float | None = Field(default=None, ge=0)
    min_width_m: float | None = Field(default=None, ge=0)
    max_width_m: float | None = Field(default=None, ge=0)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def valid_filters(self):
        if self.area_name and self.area_id:
            raise ValueError("Chỉ dùng tên khu vực hoặc mã vùng đã xác nhận.")
        for value in (self.observed_from, self.observed_to):
            if value is not None and date.fromisoformat(value).isoformat() != value:
                raise ValueError("Ngày phải có dạng YYYY-MM-DD.")
        if self.observed_from and self.observed_to:
            days = (date.fromisoformat(self.observed_to) - date.fromisoformat(self.observed_from)).days
            if not 0 <= days < 366:
                raise ValueError("Khoảng truy vấn có từ 1 đến 366 ngày, gồm cả hai đầu mốc.")
        for field in ("length_m", "width_m"):
            lo, hi = getattr(self, "min_" + field), getattr(self, "max_" + field)
            if lo is not None and hi is not None and lo > hi:
                raise ValueError("Kích thước tối thiểu phải nhỏ hơn hoặc bằng tối đa.")
        return self


class AreaRequest(AreaQueryInput):
    polygon: UserPolygon | None = None

    @model_validator(mode="after")
    def one_area(self):
        if self.polygon and (self.area_name or self.area_id):
            raise ValueError("Chỉ dùng một nguồn xác định khu vực.")
        return self


class ObservationAnalysisRequest(AreaRequest):
    analysis: Literal["dimension_mismatch", "similar_dimensions"]
    similarity_tolerance_pct: float = Field(default=10, ge=0, le=100,
        description="Sai lệch tối đa cho cả dài và rộng: 100*abs(a-b)/max(a,b).")

    @model_validator(mode="after")
    def compatible_classification(self):
        if self.analysis == "similar_dimensions" and self.classification is not None:
            raise ValueError("So sánh khác nhãn cần cả hai phân loại; bỏ classification.")
        if self.analysis == "dimension_mismatch" and self.classification not in (None, "not_aircraft_carrier"):
            raise ValueError("Truy vấn kích thước phù hợp nhưng nhãn âm cần not_aircraft_carrier.")
        return self
