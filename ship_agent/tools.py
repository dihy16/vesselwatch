"""Ship query tools using the file server by default, with an explicit mock mode."""

from copy import deepcopy
from datetime import date, timedelta
from typing import Annotated, Literal
from urllib.parse import urlencode

import httpx
from langchain_core.tools import ToolException, tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from .dates import DataSource, data_timezone, resolve_reference_date
from file_server.carrier_reports import daily_carrier_report as aggregate_carriers
from .file_server_client import FileServerError, load_daily_carrier_report, load_observations
from .mock_data import build_observations
from .map_snapshots import MapFilters, request_map
from .area_client import request_area_query
from .chat_area import apply_chat_area, chat_area_context
from file_server.area_models import AreaQueryInput

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
    elif data_source == "demo":
        from .demo_data import load_demo_observations, read_snapshot
        observations = load_demo_observations()
        demo_snapshot = read_snapshot()
    elif observations is None:
        observations = load_observations()
    metadata = {"is_mock": is_mock, "reference_date": anchor.isoformat(), "timezone": data_timezone(data_source)}
    if data_source == "demo":
        metadata.update(is_demo=True, data_scope="selected_demo_subset",
                        demo_snapshot_id=demo_snapshot["snapshot_id"])

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
    if data_source == "demo":
        source_description = "Truy vấn ảnh vệ tinh và kết quả phân loại theo thời gian quan sát."
    @tool(args_schema=CarrierReportInput)
    def daily_carrier_report(observed_from: str, observed_to: str, output_format: str = "html") -> dict:
        """Tạo báo cáo HTML hoặc ảnh chart PNG lượt dự đoán tàu sân bay theo ngày.

        Dùng khi người dùng yêu cầu báo cáo/chart/biểu đồ tàu sân bay hoặc tàu khả nghi.
        Chỉ đếm aircraft_carrier, không đếm toàn bộ tàu khả nghi. Đây là lượt
        phát hiện từ từng ảnh, không phải số tàu duy nhất hoặc nhãn đã xác nhận.
        Ngày từ caption, gồm cả hai đầu mốc, tối đa 366 ngày. Trả daily_stats,
        total_detections; hệ thống dùng chúng để đính kèm HTML vào câu trả lời.
        output_format=png khi yêu cầu ảnh chart PNG riêng; hệ thống đính kèm ảnh
        từ chart_url vào chat. Mặc định html tạo báo cáo Artifacts hoàn chỉnh.
        Mock trả số liệu giả lập và chart_url=null, vẫn dựng được báo cáo HTML.
        PNG cần server ảnh ở chế độ demo hoặc file_server; không hỗ trợ mock.
        """
        first, last = _date_range(observed_from, observed_to)
        if not 0 <= (last - first).days < 366:
            raise ToolException("Mỗi báo cáo có từ 1 đến 366 ngày.")
        if is_mock and output_format == "png":
            raise ToolException("Ảnh chart PNG cần server demo hoặc file_server; mock hỗ trợ báo cáo HTML.")
        if is_mock or data_source == "demo":
            result = aggregate_carriers(observations, first, last)
            if output_format == "png":
                from .demo_data import public_base_url
                query = urlencode({"observed_from": observed_from, "observed_to": observed_to,
                                   "report_id": result["report_id"],
                                   "snapshot_id": demo_snapshot["snapshot_id"]})
                return {**result, **metadata, "output_format": "png",
                        "chart_url": f"{public_base_url()}/charts/daily-carriers.png?{query}"}
            return {**result, **metadata, "chart_url": None}
        try:
            return {**load_daily_carrier_report(first, last),
                    "reference_date": anchor.isoformat(), "output_format": output_format}
        except FileServerError as exc:
            raise ToolException(str(exc)) from exc

    query_tools = [count_ships, search_ships, daily_carrier_report]
    if data_source == "demo":
        @tool(args_schema=MapFilters)
        def create_vessel_map(
            observed_from: str, observed_to: str, ship_id: str | None = None,
            classification: Classification | None = None,
            min_length_m: float | None = None, max_length_m: float | None = None,
            min_width_m: float | None = None, max_width_m: float | None = None,
        ) -> dict:
            """Hiển thị tàu trên bản đồ Leaflet tương tác trong HTML Artifacts.

            Dùng khi yêu cầu bản đồ/map, vị trí trên bản đồ; không dùng cho chart theo ngày.
            Khoảng ngày bắt buộc, YYYY-MM-DD gồm hai đầu mốc, tối đa 366 ngày.
            Bộ lọc ID tàu, phân loại và kích thước mét như search_ships; không phân trang.
            Lưu dữ liệu và ảnh đúng bộ lọc để có thể mở lại cùng kết quả trên bản đồ.
            Trả URL và số lượt quan sát; hệ thống đính kèm iframe, không đưa HTML map cho LLM.
            """
            filters = MapFilters(
                observed_from=observed_from, observed_to=observed_to, ship_id=ship_id,
                classification=classification, min_length_m=min_length_m, max_length_m=max_length_m,
                min_width_m=min_width_m, max_width_m=max_width_m,
            )
            try:
                return {**request_map(filters, demo_snapshot["snapshot_id"]), **metadata}
            except (httpx.HTTPError, ValueError) as exc:
                raise ToolException("Chưa tạo được bản đồ. Kiểm tra server demo cổng 8002 và snapshot; "
                                    "khởi động lại agent/server nếu đã đổi dữ liệu.") from exc

        query_tools.append(create_vessel_map)

    if not is_mock:
        @tool(args_schema=ChatAreaQueryInput)
        def query_ships_in_area(
            area_name: str | None = None, area_id: str | None = None,
            observed_from: str | None = None, observed_to: str | None = None,
            classification: Classification | None = None, ship_id: str | None = None,
            length_gt_m: float | None = None,
            min_length_m: float | None = None, max_length_m: float | None = None,
            min_width_m: float | None = None, max_width_m: float | None = None,
            limit: int = 20, offset: int = 0,
            use_chat_area: bool = False, config: RunnableConfig = None,
        ) -> dict:
            """Truy vấn lượt phát hiện theo vùng, ngày, kích thước và nhãn.

            Chỉ Biển Đông và Vịnh Bắc Bộ có polygon lưu sẵn. Mọi tên vùng khác
            hoặc mô tả mơ hồ trả needs_drawing và map_url để người dùng tự vẽ,
            xác nhận bằng nút trên map; không tự đoán vùng. area_id là mã vùng
            người dùng đã xác nhận, không phải selection_id chưa được xác nhận.
            Bỏ cả area_name/area_id để tìm vị trí toàn bộ dữ liệu (ví dụ tàu dài
            trên 250 m: length_gt_m=250). Lọc toàn bộ nguồn trước khi phân trang.
            total là số observation_id khác nhau, không phải số tàu duy nhất.
            Nhãn aircraft_carrier dùng prediction đã lưu, không áp lại ngưỡng score.
            Ngày YYYY-MM-DD, gồm hai đầu mốc; không có ngày thì tìm toàn bộ nguồn.
            Với 'vùng này/vùng vừa vẽ/vùng đang chọn', dùng use_chat_area=true,
            bỏ area_name/area_id. Runtime tự cung cấp polygon đã xác nhận của chat;
            không tự nhập tọa độ hoặc lấy mã vùng cũ từ lịch sử. Chưa chọn vùng
            thì báo cần xác nhận, không chuyển thành truy vấn toàn bộ dữ liệu.
            """
            query = AreaQueryInput(
                area_name=area_name, area_id=area_id, observed_from=observed_from,
                observed_to=observed_to, classification=classification, ship_id=ship_id,
                length_gt_m=length_gt_m, min_length_m=min_length_m, max_length_m=max_length_m,
                min_width_m=min_width_m, max_width_m=max_width_m, limit=limit, offset=offset,
            )
            try:
                context = chat_area_context(config)
                payload = apply_chat_area(query.model_dump(), config) if use_chat_area else query.model_dump()
                result = request_area_query(payload, data_source=data_source)
                if context:
                    # The model needs counts/status, not the chat session's URL capability.
                    result = {**result, "persistent_map": True}
                    result.pop("map_url", None)
                    if result.get("status") == "needs_drawing":
                        result["message"] = "Vẽ/chọn vùng trên map của cuộc chat rồi bấm Xác nhận; gửi 'map' nếu chưa mở."
                if use_chat_area:
                    result.pop("area_id", None)
                    result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
                return result
            except (httpx.HTTPError, ValueError) as exc:
                if use_chat_area and isinstance(exc, ValueError):
                    raise ToolException(str(exc)) from exc
                raise ToolException("Chưa truy vấn được vùng. Kiểm tra data server và mã vùng; "
                                    "nếu dữ liệu đã đổi, hãy tạo lại vùng.") from exc

        query_tools.append(query_ships_in_area)

    if not is_mock:
        from .image_review import create_image_review_tool
        query_tools.append(create_image_review_tool(observations, data_source=data_source))

    for query_tool in query_tools:
        query_tool.description += f"\nMúi giờ: {metadata['timezone']}. {source_description}"
    return query_tools
