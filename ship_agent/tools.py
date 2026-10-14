"""Ship query tools using the file server by default, with an explicit mock mode."""

from copy import deepcopy
from datetime import date, timedelta
from typing import Annotated, Literal

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, ConfigDict, Field

from .dates import DataSource, data_timezone, resolve_reference_date
from file_server.carrier_reports import daily_carrier_report as aggregate_carriers
from .file_server_client import FileServerError, load_daily_carrier_report, load_observations
from .mock_data import build_observations

DateString = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Ngày YYYY-MM-DD theo múi giờ của nguồn dữ liệu (mặc định UTC).")]
Classification = Literal["aircraft_carrier", "not_aircraft_carrier", "unknown"]


class CountShipsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_from: DateString
    observed_to: DateString


class SearchShipsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_from: DateString | None = None
    observed_to: DateString | None = None
    ship_id: str | None = Field(default=None, description="Tên tàu chính xác từ dòng '- Tàu:' trong caption Telegram (mock: SHIP_001).")
    min_length_m: float | None = Field(default=None, ge=0)
    max_length_m: float | None = Field(default=None, ge=0)
    min_width_m: float | None = Field(default=None, ge=0)
    max_width_m: float | None = Field(default=None, ge=0)
    classification: Classification | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


def _date_range(start: str | None, end: str | None) -> tuple[date | None, date | None]:
    try:
        first = date.fromisoformat(start) if start else None
        last = date.fromisoformat(end) if end else None
    except ValueError as exc:
        raise ToolException("Ngày không hợp lệ; dùng YYYY-MM-DD.") from exc
    if first and last and first > last:
        raise ToolException("observed_from phải nhỏ hơn hoặc bằng observed_to.")
    return first, last


def create_tools(reference_date: date | None = None, *, data_source: DataSource = "file_server",
                 observations: list[dict] | None = None):
    """Load a complete snapshot at creation, or reuse a preloaded server snapshot."""
    anchor = resolve_reference_date(reference_date, data_source)
    is_mock = data_source == "mock"
    if is_mock:
        observations = build_observations(anchor)
    elif observations is None:
        observations = load_observations()
    metadata = {"is_mock": is_mock, "reference_date": anchor.isoformat(), "timezone": data_timezone(data_source)}

    def latest_in_range(first, last, per_day=False):
        latest = {}
        for observation in observations:
            day = date.fromisoformat(observation["observed_date"])
            if (first and day < first) or (last and day > last):
                continue
            identity = observation["ship_id"] if is_mock else observation["observation_id"]
            key = (day, identity) if per_day else identity
            if key not in latest or observation["observed_at"] > latest[key]["observed_at"]:
                latest[key] = observation
        return list(latest.values())

    @tool(args_schema=CountShipsInput)
    def count_ships(observed_from: str, observed_to: str) -> dict:
        """Thống kê tàu khả nghi và tàu có khả năng là tàu sân bay theo từng ngày.

        Ngày YYYY-MM-DD, gồm cả hai đầu mốc, tối đa 366 ngày mỗi lần gọi.
        Đếm ID tàu duy nhất trong ngày, dùng phân loại của lần quan sát cuối ngày.
        Với dữ liệu thật, mỗi ảnh Telegram được đếm riêng dù trùng tên tàu trong caption.
        aircraft_carrier là kết quả mô hình, không phải xác nhận thực tế.
        Ngày không có quan sát trả 0. Lỗi nguồn dữ liệu được báo lỗi, không tính là 0.
        """
        first, last = _date_range(observed_from, observed_to)
        if (last - first).days >= 366:
            raise ToolException("Mỗi lần thống kê tối đa 366 ngày; hãy chia nhỏ khoảng ngày.")
        by_day = {}
        for observation in latest_in_range(first, last, per_day=True):
            by_day.setdefault(observation["observed_date"], []).append(observation)
        stats = []
        for offset in range((last - first).days + 1):
            day = (first + timedelta(days=offset)).isoformat()
            ships = by_day.get(day, [])
            stats.append({
                "date": day,
                "suspicious_ship_count": len(ships),
                "possible_aircraft_carrier_count": sum(s["classification"] == "aircraft_carrier" for s in ships),
            })
        return {**metadata, "observed_from": observed_from, "observed_to": observed_to, "daily_stats": stats}

    @tool(args_schema=SearchShipsInput)
    def search_ships(
        observed_from: str | None = None, observed_to: str | None = None,
        ship_id: str | None = None,
        min_length_m: float | None = None, max_length_m: float | None = None,
        min_width_m: float | None = None, max_width_m: float | None = None,
        classification: Classification | None = None, limit: int = 20, offset: int = 0,
    ) -> dict:
        """Tìm tàu khả nghi, trả URL chi tiết, kích thước, vị trí, ngày giờ, phân loại và URL ảnh.

        Ngày YYYY-MM-DD và kích thước mét, gồm cả hai đầu mốc; bộ lọc có thể bỏ qua.
        Chọn lần quan sát mới nhất của mỗi tàu trong khoảng ngày TRƯỚC khi lọc
        kích thước/phân loại. Dùng ship_id để xem riêng một tàu. Có phân trang.
        Với dữ liệu thật, mỗi ảnh là một kết quả riêng; ship_id lấy từ caption Telegram.
        confidence là carrier score; null nếu chưa có prediction.
        """
        first, last = _date_range(observed_from, observed_to)
        for minimum, maximum, field in [(min_length_m, max_length_m, "length_m"), (min_width_m, max_width_m, "width_m")]:
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ToolException(f"min_{field} phải nhỏ hơn hoặc bằng max_{field}.")
        matches = []
        for observation in latest_in_range(first, last):
            if ship_id is not None and observation["ship_id"] != ship_id:
                continue
            if classification is not None and observation["classification"] != classification:
                continue
            if any((minimum is not None and observation[field] < minimum) or
                   (maximum is not None and observation[field] > maximum)
                   for minimum, maximum, field in [(min_length_m, max_length_m, "length_m"), (min_width_m, max_width_m, "width_m")]):
                continue
            matches.append(observation)
        matches.sort(key=lambda item: item["ship_id"])
        filters = {"observed_from": observed_from, "observed_to": observed_to, "ship_id": ship_id,
                   "min_length_m": min_length_m, "max_length_m": max_length_m,
                   "min_width_m": min_width_m, "max_width_m": max_width_m, "classification": classification}
        return {**metadata, "filters": filters, "total": len(matches), "limit": limit, "offset": offset,
                "ships": deepcopy(matches[offset:offset + limit])}

    source_description = ("Dữ liệu và URL giả lập." if is_mock else
                          "Dữ liệu thật từ file server; mỗi ảnh Telegram là một tàu riêng.")
    @tool(args_schema=CountShipsInput)
    def daily_carrier_report(observed_from: str, observed_to: str) -> dict:
        """Tạo báo cáo và biểu đồ PNG lượt dự đoán tàu sân bay theo từng ngày.

        Dùng khi người dùng yêu cầu báo cáo/chart/biểu đồ tàu sân bay hoặc tàu khả nghi.
        Chỉ đếm aircraft_carrier, không đếm toàn bộ tàu khả nghi. Đây là lượt
        phát hiện từ từng ảnh, không phải số tàu duy nhất hoặc nhãn đã xác nhận.
        Ngày từ caption, gồm cả hai đầu mốc, tối đa 366 ngày. Trả daily_stats,
        total_detections và chart_url cho Markdown ảnh; không tự tạo URL.
        Mock chỉ trả số liệu giả lập và chart_url=null, không có ảnh chart thật.
        """
        first, last = _date_range(observed_from, observed_to)
        if not 0 <= (last - first).days < 366:
            raise ToolException("Mỗi báo cáo có từ 1 đến 366 ngày.")
        if is_mock:
            result = aggregate_carriers(observations, first, last)
            return {**result, **metadata, "chart_url": None}
        try:
            return {**load_daily_carrier_report(first, last),
                    "reference_date": anchor.isoformat()}
        except FileServerError as exc:
            raise ToolException(str(exc)) from exc

    for query_tool in (count_ships, search_ships, daily_carrier_report):
        query_tool.description += f"\nMúi giờ: {metadata['timezone']}. {source_description}"
    return [count_ships, search_ships, daily_carrier_report]
