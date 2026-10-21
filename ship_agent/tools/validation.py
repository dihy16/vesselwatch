"""Tool-level date validation with the existing user-visible errors."""

from datetime import date

from langchain_core.tools import ToolException


def _date_range(start: str | None, end: str | None) -> tuple[date | None, date | None]:
    try:
        first = date.fromisoformat(start) if start else None
        last = date.fromisoformat(end) if end else None
    except ValueError as exc:
        raise ToolException("Ngày không hợp lệ; dùng YYYY-MM-DD.") from exc
    if first and last and first > last:
        raise ToolException("observed_from phải nhỏ hơn hoặc bằng observed_to.")
    return first, last
