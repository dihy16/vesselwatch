"""Public input schemas for query, report and review tools."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from file_server.schemas.area_models import AreaQueryInput
from file_server.schemas.reviews import FalseCarrierScope, MissedCarrierScope


DateString = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Ngày YYYY-MM-DD theo múi giờ của nguồn dữ liệu (mặc định UTC).")]
Classification = Literal["aircraft_carrier", "not_aircraft_carrier", "unknown"]


class CountShipsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_from: DateString
    observed_to: DateString


class CarrierReportInput(CountShipsInput):
    output_format: Literal["html", "png"] = Field(
        default="html", description="html: báo cáo Artifacts; png: ảnh chart riêng trong chat.",
    )


class ChatAreaQueryInput(AreaQueryInput):
    use_chat_area: bool = Field(
        default=False,
        description="Dùng đúng một vùng đã xác nhận trên map của cuộc chat hiện tại; bỏ area_name và area_id.",
    )


class ObservationAnalysisInput(ChatAreaQueryInput):
    analysis: Literal["dimension_mismatch", "similar_dimensions"] = Field(
        description="dimension_mismatch: kích thước phù hợp nhưng nhãn âm; similar_dimensions: cặp khác nhãn có kích thước tương đồng.")
    similarity_tolerance_pct: float = Field(default=10, ge=0, le=100)


class SearchShipsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    observed_from: DateString | None = None
    observed_to: DateString | None = None
    ship_id: str | None = Field(default=None, description="Tên tàu chính xác từ dòng '- Tàu:' trong caption Telegram (mock: SHIP_001).")
    min_length_m: float | None = Field(default=None, ge=0)
    max_length_m: float | None = Field(default=None, ge=0)
    min_width_m: float | None = Field(default=None, ge=0)
    max_width_m: float | None = Field(default=None, ge=0)
    length_gt_m: float | None = Field(default=None, ge=0)
    carrier_score_gt: float | None = Field(default=None, ge=0, le=1)
    classification: Classification | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class FalseCarrierToolInput(FalseCarrierScope):
    use_chat_area: bool = Field(default=False,
        description="Dùng vùng đã xác nhận của chat; bỏ area_name và area_id. Bỏ vùng để lọc toàn nguồn theo ngày.")

class MissedCarrierToolInput(MissedCarrierScope):
    use_chat_area: bool = Field(default=False,
        description="Dùng vùng đã xác nhận của chat; bỏ area_name và area_id. Không có vùng thì lọc toàn nguồn theo ngày.")
