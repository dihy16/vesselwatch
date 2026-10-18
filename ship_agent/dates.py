"""Reference dates for real UTC observations and the optional mock dataset."""

from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

DataSource = Literal["file_server", "mock", "demo"]


def data_timezone(data_source: DataSource) -> str:
    if data_source in {"file_server", "demo"}:
        return "UTC"
    if data_source == "mock":
        return "Asia/Ho_Chi_Minh"
    raise ValueError("data_source must be 'file_server', 'mock', or 'demo'.")


def resolve_reference_date(reference_date: date | None, data_source: DataSource) -> date:
    name = data_timezone(data_source)
    if reference_date is not None:
        return reference_date
    if data_source == "demo":
        from .demo_data import DEMO_REFERENCE_DATE
        return DEMO_REFERENCE_DATE
    tz = timezone.utc if name == "UTC" else ZoneInfo(name)
    return datetime.now(tz).date()
