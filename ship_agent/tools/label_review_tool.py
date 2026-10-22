"""BR 19: prioritize saved positives by score, inspect pixels and group label-review evidence."""

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool

from file_server.schemas.reviews import FalseCarrierScope, FalseCarrierRequest
from ship_agent.clients.carrier_reference_client import load_carrier_references
from ship_agent.clients.label_review_client import request_label_review_candidates
from ship_agent.runtime.chat_area import apply_chat_area, chat_area_context
from ship_agent.runtime.visual_context import attach_visual_input
from ship_agent.tools.schemas import FalseCarrierToolInput
from ship_agent.workflows.label_review import run_label_investigation


def create_label_review_tool():
    @tool(args_schema=FalseCarrierToolInput)
    def investigate_carrier_labels(
        observed_from: str, observed_to: str, area_name: str | None = None, area_id: str | None = None,
        center_latitude: float | None = None, center_longitude: float | None = None, radius_nm: float | None = None,
        use_chat_area: bool = False, limit: int = 20, offset: int = 0, config: RunnableConfig = None,
    ) -> dict:
        """Câu 19: giảm false positive bằng review toàn bộ nhãn tàu sân bay, score thấp trước.

        Ngày bắt buộc, vùng tùy chọn; use_chat_area=true cho vùng vừa vẽ. Không
        đặt cận trên/dưới score hoặc kích thước; giữ cả score cao và thiếu score.
        Sắp score tăng dần trên toàn phạm vi trước phân trang, thiếu score cuối.
        ĐỌC từng ảnh (kể cả <300 m), đối chiếu hình dáng tổng thể/màu thân với
        toàn bộ bộ mẫu. Phân nhóm: nghi false positive, phù hợp mẫu, chưa đủ
        bằng chứng, ảnh chưa đủ rõ, lỗi review. Chỉ sufficient có khác biệt
        được dẫn mẫu mới flag/đề xuất xác minh-bổ sung nhãn thủ công.
        Mờ/unknown không flag, không suy ra cơ chế nội bộ classifier, không
        tự sửa nhãn. Thống kê score/kích thước là toàn phạm vi; nhóm/bằng chứng
        chỉ thuộc trang đã đọc. limit/offset mặc định 20/0; báo rõ next_offset.
        """
        try:
            scope = FalseCarrierScope(observed_from=observed_from, observed_to=observed_to,
                                      center_latitude=center_latitude, center_longitude=center_longitude, radius_nm=radius_nm,
                                      area_name=area_name, area_id=area_id, limit=limit, offset=offset)
            context = chat_area_context(config)
            payload = apply_chat_area(scope.model_dump(), config) if use_chat_area else scope.model_dump()
            payload = FalseCarrierRequest.model_validate(payload).model_dump()
        except ValueError as exc:
            raise ToolException(str(exc)) from exc
        try:
            candidates = request_label_review_candidates(payload)
        except (ValueError, httpx.HTTPError, OSError) as exc:
            raise ToolException("Chưa lấy được danh sách kiểm tra nhãn; kiểm tra ngày/vùng và file server.") from exc
        if candidates["status"] == "needs_drawing":
            if context:
                candidates = {**candidates, "persistent_map": True,
                              "message": "Vẽ/chọn vùng trên map rồi bấm Xác nhận trước khi kiểm tra nhãn."}
                candidates.pop("map_url", None)
            return candidates

        def create_reviewer():
            from ship_agent.vision.image_review import _vision_model, review_image_against_references
            model = _vision_model()
            return lambda row, refs: review_image_against_references(row, refs, model=model)

        result, library = run_label_investigation(candidates, load_library=load_carrier_references,
                                                 create_reviewer=create_reviewer)
        reviewed_ids = {item["observation_id"] for item in result["flags"] + result["unflagged"]}
        if reviewed_ids:
            result = attach_visual_input(result, [row for row in candidates["ships"]
                                                  if row["observation_id"] in reviewed_ids], library)
        if use_chat_area:
            result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
        return result

    return investigate_carrier_labels
