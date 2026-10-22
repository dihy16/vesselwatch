"""Create demo map snapshots without putting HTML in model context."""

import httpx
from langchain_core.tools import ToolException, tool

from ship_agent.artifacts.map_snapshots import MapFilters, request_map
from ship_agent.tools.schemas import Classification


def create_map_tools(context):
    demo_snapshot, metadata = context.demo_snapshot, context.metadata

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

    return [create_vessel_map]
