"""BR 17: dimension-first investigation of saved carrier-positive detections."""

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool

from file_server.false_carriers import FalseCarrierRequest, FalseCarrierScope
from .area_client import request_carrier_investigation_candidates
from .carrier_investigation import run_carrier_investigation
from .carrier_reference_client import load_carrier_references
from .chat_area import apply_chat_area, chat_area_context
from .false_carrier_tool import FalseCarrierToolInput
from .visual_context import attach_visual_input


def create_carrier_investigation_tool():
    @tool(args_schema=FalseCarrierToolInput)
    def investigate_carrier_detections(
        observed_from: str, observed_to: str, area_name: str | None = None, area_id: str | None = None,
        use_chat_area: bool = False, limit: int = 20, offset: int = 0,
        config: RunnableConfig = None,
    ) -> dict:
        """Câu 17: điều tra nhãn tàu sân bay và tổng hợp ưu tiên kiểm tra thủ công.

        Khoảng ngày bắt buộc; dùng use_chat_area=true cho vùng vừa vẽ, hoặc area_name/area_id.
        Nhãn aircraft_carrier, không thêm ngưỡng score. Ưu tiên 1: dài <300 m,
        đưa vào danh sách ngay KHÔNG đọc ảnh. Còn lại (kể cả thiếu chiều dài)
        đối chiếu mô tả và toàn bộ ảnh mẫu; ưu tiên 2 chỉ khi ảnh đủ rõ có bằng
        chứng hình dáng tổng thể/màu thân nghi không phải tàu sân bay như câu 16.
        300 m chính xác đi nhánh ảnh; ảnh mờ/unknown không flag. Giữ nhãn gốc.
        Sắp nhóm <300 m trên TOÀN BỘ nguồn đã lọc trước khi phân trang limit/offset.
        Báo riêng số lọc kích thước, đã đọc ảnh, lỗi, tổng ứng viên, next_offset;
        counts ưu tiên là của trang này, không khẳng định đã điều tra toàn bộ.
        """
        try:
            scope = FalseCarrierScope(observed_from=observed_from, observed_to=observed_to,
                                      area_name=area_name, area_id=area_id, limit=limit, offset=offset)
            context = chat_area_context(config)
            payload = apply_chat_area(scope.model_dump(), config) if use_chat_area else scope.model_dump()
            payload = FalseCarrierRequest.model_validate(payload).model_dump()
        except ValueError as exc:
            raise ToolException(str(exc)) from exc
        try:
            candidates = request_carrier_investigation_candidates(payload)
        except (ValueError, httpx.HTTPError, OSError) as exc:
            raise ToolException("Chưa lấy được ứng viên điều tra; kiểm tra ngày/vùng và file server.") from exc
        if candidates["status"] == "needs_drawing":
            if context:
                candidates = {**candidates, "persistent_map": True,
                              "message": "Vẽ/chọn vùng trên map rồi bấm Xác nhận trước khi điều tra."}
                candidates.pop("map_url", None)
            return candidates

        def create_reviewer():
            from .image_review import _vision_model, review_image_against_references
            model = _vision_model()
            return lambda row, refs: review_image_against_references(row, refs, model=model)

        result, library = run_carrier_investigation(candidates, load_library=load_carrier_references,
                                                   create_reviewer=create_reviewer)
        reviewed_ids = {item["observation_id"] for item in result["flags"] + result["unflagged"]
                        if item["reference_comparison_performed"]}
        if reviewed_ids:
            result = attach_visual_input(result, [row for row in candidates["ships"]
                                                  if row["observation_id"] in reviewed_ids], library)
        if use_chat_area:
            result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
        return result

    return investigate_carrier_detections
