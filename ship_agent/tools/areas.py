"""Spatial querying and cross-label observation analysis."""

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool

from file_server.schemas.area_models import AreaQueryInput, ObservationAnalysisRequest
from ship_agent.clients.area_client import request_area_query, request_observation_analysis
from ship_agent.runtime.chat_area import apply_chat_area, chat_area_context
from ship_agent.tools.schemas import ChatAreaQueryInput, ObservationAnalysisInput, Classification


def create_area_tools(context):
    data_source = context.data_source

    @tool(args_schema=ChatAreaQueryInput)
    def query_ships_in_area(
        area_name: str | None = None, area_id: str | None = None,
        observed_from: str | None = None, observed_to: str | None = None,
        classification: Classification | None = None, ship_id: str | None = None,
        length_gt_m: float | None = None,
        carrier_score_gt: float | None = None,
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
        Nhãn dùng phân loại từ nguồn. carrier_score_gt là lọc score lớn hơn nghiêm ngặt
        (trên 80%: carrier_score_gt=0.8), không đổi nhãn. null không khớp bộ lọc score.
        Ngày YYYY-MM-DD, gồm hai đầu mốc; không có ngày thì tìm toàn bộ nguồn.
        Với 'vùng này/vùng vừa vẽ/vùng đang chọn', dùng use_chat_area=true,
        bỏ area_name/area_id. Runtime tự cung cấp polygon đã xác nhận của chat;
        không tự nhập tọa độ hoặc lấy mã vùng cũ từ lịch sử. Chưa chọn vùng
        thì báo cần xác nhận, không chuyển thành truy vấn toàn bộ dữ liệu.
        """
        query = AreaQueryInput(
            area_name=area_name, area_id=area_id, observed_from=observed_from,
            observed_to=observed_to, classification=classification, ship_id=ship_id,
            length_gt_m=length_gt_m, carrier_score_gt=carrier_score_gt,
            min_length_m=min_length_m, max_length_m=max_length_m,
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

    @tool(args_schema=ObservationAnalysisInput)
    def analyze_ship_observations(
        analysis: str, similarity_tolerance_pct: float = 10,
        area_name: str | None = None, area_id: str | None = None,
        observed_from: str | None = None, observed_to: str | None = None,
        classification: Classification | None = None, ship_id: str | None = None,
        length_gt_m: float | None = None, carrier_score_gt: float | None = None,
        min_length_m: float | None = None, max_length_m: float | None = None,
        min_width_m: float | None = None, max_width_m: float | None = None,
        limit: int = 20, offset: int = 0,
        use_chat_area: bool = False, config: RunnableConfig = None,
    ) -> dict:
        """Phân tích kích thước và kết quả nhận dạng trên toàn bộ observations trước phân trang.

        dimension_mismatch: tìm kích thước phù hợp tàu sân bay nhưng nhãn
        not_aircraft_carrier. Mặc định dài 250–350m và rộng 50–80m (gồm biên),
        cho phép thay khoảng kích thước theo câu hỏi. Đây là tiêu chí lọc.
        similar_dimensions: cặp observations có nhãn aircraft_carrier và
        not_aircraft_carrier, sai lệch CẢ dài và rộng không quá
        similarity_tolerance_pct (mặc định 10%). Sai lệch = 100*abs(a-b)/max(a,b).
        Bỏ classification khi so sánh cặp; không mặc định giới hạn kích thước.
        total là số cặp ở chế độ so sánh, không phải số tàu hay cùng một tàu.
        Dùng use_chat_area=true cho vùng chat; bỏ vùng để phân tích toàn nguồn.
        Không lấy trang kết quả search_ships rồi tự suy ra số lượng toàn bộ.
        """
        try:
            query = AreaQueryInput(
                area_name=area_name, area_id=area_id, observed_from=observed_from,
                observed_to=observed_to, classification=classification, ship_id=ship_id,
                length_gt_m=length_gt_m, carrier_score_gt=carrier_score_gt,
                min_length_m=min_length_m, max_length_m=max_length_m,
                min_width_m=min_width_m, max_width_m=max_width_m, limit=limit, offset=offset)
            context = chat_area_context(config)
            payload = apply_chat_area(query.model_dump(), config) if use_chat_area else query.model_dump()
            payload.update(analysis=analysis, similarity_tolerance_pct=similarity_tolerance_pct)
            payload = ObservationAnalysisRequest.model_validate(payload).model_dump()
            result = request_observation_analysis(payload, data_source=data_source)
            if context:
                result = {**result, "persistent_map": True}
                result.pop("map_url", None)
                if result.get("status") == "needs_drawing":
                    result["message"] = "Vẽ/chọn vùng trên map rồi bấm Xác nhận; gửi 'map' nếu chưa mở."
            if use_chat_area:
                result.pop("area_id", None)
                result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
            return result
        except ValueError as exc:
            raise ToolException(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ToolException("Chưa phân tích được dữ liệu. Kiểm tra file server; không dùng kết quả cũ.") from exc

    return [query_ships_in_area, analyze_ship_observations]
