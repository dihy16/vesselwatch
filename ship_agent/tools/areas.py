"""Spatial querying and cross-label observation analysis."""

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool

from file_server.schemas.area_models import AreaQueryInput, ObservationAnalysisRequest
from ship_agent.clients.area_client import request_area_query, request_observation_analysis
from ship_agent.clients.chat_area_client import save_chat_area, selection_area, selection_context
from ship_agent.runtime.chat_area import apply_chat_area, chat_area_context
from ship_agent.tools.schemas import ChatAreaQueryInput, ObservationAnalysisInput, Classification


def create_area_tools(context):
    data_source = context.data_source

    @tool(args_schema=ChatAreaQueryInput, response_format="content_and_artifact")
    def query_ships_in_area(
        area_name: str | None = None, area_id: str | None = None,
        center_latitude: float | None = None, center_longitude: float | None = None,
        radius_nm: float | None = None,
        observed_from: str | None = None, observed_to: str | None = None,
        classification: Classification | None = None, ship_id: str | None = None,
        length_gt_m: float | None = None,
        carrier_score_gt: float | None = None,
        min_length_m: float | None = None, max_length_m: float | None = None,
        min_width_m: float | None = None, max_width_m: float | None = None,
        limit: int = 20, offset: int = 0,
        use_chat_area: bool = False, set_as_chat_area: bool = False, config: RunnableConfig = None,
    ) -> tuple:
        """Truy vấn lượt phát hiện theo vùng, ngày, kích thước và nhãn.

        Biển Đông và Vịnh Bắc Bộ có polygon lưu sẵn. Thanh Đảo (Yuchi),
        Du Lâm, Long Pha (Du Lâm Đông) có tâm cố định: truyền area_name
        và radius_nm theo người dùng. Hoặc truyền center_latitude,
        center_longitude do người dùng cung cấp cùng radius_nm, bỏ area_name.
        radius_nm=20 mở rộng 20 hải lý mỗi hướng, ô vuông cạnh khoảng 40 hải lý,
        không lọc theo hình tròn. Chưa có khoảng cách thì hỏi thêm, không tự chọn.
        Mọi tên vùng khác
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
        Khi người dùng yêu cầu CHỌN/ĐỔI vùng cho cuộc chat, dùng set_as_chat_area=true
        với tên có sẵn hoặc hình vuông từ tâm/radius_nm. Lưu vùng và hiện lên map;
        các câu tiếp theo dùng use_chat_area=true. Truy vấn thông thường để false.
        Không kèm use_chat_area=true; chọn vùng bằng một tool call riêng trước khi
        gọi các tool khác dùng vùng đó. Không cần ngày nếu chỉ chọn vùng.
        """
        query = AreaQueryInput(
            area_name=area_name, area_id=area_id, observed_from=observed_from,
            center_latitude=center_latitude, center_longitude=center_longitude, radius_nm=radius_nm,
            observed_to=observed_to, classification=classification, ship_id=ship_id,
            length_gt_m=length_gt_m, carrier_score_gt=carrier_score_gt,
            min_length_m=min_length_m, max_length_m=max_length_m,
            min_width_m=min_width_m, max_width_m=max_width_m, limit=limit, offset=offset,
        )
        try:
            context = chat_area_context(config)
            area = None
            if set_as_chat_area:
                if use_chat_area:
                    raise ValueError("Không chọn vùng mới và dùng vùng đã lưu cùng lúc.")
                selection_context(context)
                area = selection_area(query)
            payload = apply_chat_area(query.model_dump(), config) if use_chat_area else query.model_dump()
            result = request_area_query(payload, data_source=data_source)
            artifact = None
            if set_as_chat_area:
                if result.get("status") != "complete":
                    raise ValueError("Chưa xác định được vùng để lưu; hãy chọn vùng có sẵn hoặc vẽ trên map.")
                saved = save_chat_area(context, area)
                artifact = {"chat_area_selection": saved}
                result = {**result, "chat_area_selected": True, "chat_area_revision": saved["revision"],
                          "query_scope": "chat_active_area",
                          "message": "Đã lưu vùng đang chọn của chat. Map sẽ tự cập nhật; câu tiếp theo có thể hỏi về vùng này."}
            if context:
                # The model needs counts/status, not the chat session's URL capability.
                result = {**result, "persistent_map": True}
                result.pop("map_url", None)
                if result.get("status") == "needs_drawing":
                    result["message"] = "Vẽ/chọn vùng trên map của cuộc chat rồi bấm Xác nhận; gửi 'map' nếu chưa mở."
            if use_chat_area:
                result.pop("area_id", None)
                result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
            return result, artifact
        except (httpx.HTTPError, ValueError) as exc:
            if set_as_chat_area:
                raise ToolException("Chưa xác nhận chọn/lưu vùng thành công. Kiểm tra map, MAP_API_URL của LangGraph và phiên bản vùng; tải lại vùng rồi thử lại.") from exc
            if use_chat_area and isinstance(exc, ValueError):
                raise ToolException(str(exc)) from exc
            raise ToolException("Chưa truy vấn được vùng. Kiểm tra data server và mã vùng; "
                                "nếu dữ liệu đã đổi, hãy tạo lại vùng.") from exc

    @tool(args_schema=ObservationAnalysisInput)
    def analyze_ship_observations(
        analysis: str, similarity_tolerance_pct: float = 10,
        area_name: str | None = None, area_id: str | None = None,
        center_latitude: float | None = None, center_longitude: float | None = None,
        radius_nm: float | None = None,
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
                center_latitude=center_latitude, center_longitude=center_longitude, radius_nm=radius_nm,
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
