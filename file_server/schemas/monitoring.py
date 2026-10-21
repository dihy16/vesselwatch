"""Monitoring report scope validation."""

from pydantic import model_validator

from file_server.schemas.geometry import UserPolygon
from file_server.schemas.reviews import CarrierReviewScope


class MonitoringScope(CarrierReviewScope):
    """limit/offset select the detailed-review page, never truncate statistics."""

    @model_validator(mode="after")
    def previous_month_exists(self):
        if self.observed_from.startswith("0001-01"):
            raise ValueError("Khoảng báo cáo cần có tháng dương lịch liền trước để đối chiếu.")
        return self

class MonitoringRequest(MonitoringScope):
    polygon: UserPolygon | None = None
