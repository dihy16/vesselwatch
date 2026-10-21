"""Validated area-query arguments shared by the agent and data API."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .spatial import AREA_CENTERS, UserPolygon, named_center, square_polygon


class AreaQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    area_name: str | None = Field(default=None, max_length=160)
    area_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    center_latitude: float | None = Field(default=None, gt=-90, lt=90,
        description="Vĩ độ tâm do người dùng cung cấp; dùng cùng center_longitude và radius_nm.")
    center_longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_nm: float | None = Field(default=None, gt=0,
        description="Khoảng cách từ tâm về mỗi hướng Bắc/Nam/Đông/Tây, đơn vị hải lý; cạnh ô vuông xấp xỉ 2 lần giá trị này. Dùng với căn cứ đã lưu hoặc tọa độ người dùng.")
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
        has_center = self.center_latitude is not None or self.center_longitude is not None
        if has_center and (self.center_latitude is None or self.center_longitude is None
                           or self.area_name or self.area_id):
            raise ValueError("Nhập đủ vĩ độ và kinh độ tâm; không dùng kèm tên hoặc mã vùng.")
        key = named_center(self.area_name)
        if (has_center or key) and self.radius_nm is None:
            raise ValueError("Hãy nhập khoảng cách mở rộng từ tâm, đơn vị hải lý (radius_nm).")
        if self.radius_nm is not None:
            if not has_center and not key:
                raise ValueError("Khoảng cách cần đi kèm tọa độ tâm hoặc tên căn cứ đã lưu: Thanh Đảo, Du Lâm, Long Pha.")
            center = AREA_CENTERS[key] if key else {"latitude": self.center_latitude, "longitude": self.center_longitude}
            square_polygon(center["latitude"], center["longitude"], self.radius_nm)
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
        if self.polygon and (self.area_name or self.area_id or self.radius_nm is not None
                             or self.center_latitude is not None):
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
