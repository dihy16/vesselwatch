"""Review saved carrier positives for evidence that warrants manual inspection."""

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool

from file_server.schemas.reviews import FalseCarrierRequest, FalseCarrierScope
from ship_agent.clients.area_client import request_false_carrier_candidates
from ship_agent.clients.carrier_reference_client import load_carrier_references
from ship_agent.runtime.chat_area import apply_chat_area, chat_area_context
from ship_agent.runtime.visual_context import attach_visual_input
from ship_agent.tools.schemas import FalseCarrierToolInput
from ship_agent.vision.false_carrier_evidence import build_false_carrier_evidence
from ship_agent.workflows.reference_review import run_reference_reviews


def create_false_carrier_tool():
    @tool(args_schema=FalseCarrierToolInput)
    def investigate_false_carriers(
        observed_from: str, observed_to: str, area_name: str | None = None, area_id: str | None = None,
        use_chat_area: bool = False, limit: int = 20, offset: int = 0,
        config: RunnableConfig = None,
    ) -> dict:
        """Câu 16: kiểm tra ảnh nhãn aircraft_carrier nhưng có thể không phải tàu sân bay.

        Khoảng ngày bắt buộc, vùng tùy chọn; use_chat_area=true cho vùng vừa vẽ.
        Lấy TẤT CẢ observations mang nhãn aircraft_carrier trong phạm vi trước
        phân trang, không thêm ngưỡng score/kích thước. Đối chiếu từng TARGET
        với mô tả và toàn bộ ảnh mẫu, chỉ dùng hình dáng tổng thể/màu phần thân.
        Chỉ flag ảnh sufficient có nhận xét not_aircraft_carrier, đặc điểm nhìn
        thấy và khác biệt cụ thể dẫn đến reference_id có thật. Không cần xác
        định tàu hàng/container. Khác một mẫu, màu đơn lẻ hoặc ảnh mờ chưa đủ.
        Flag để kiểm tra thủ công, không sửa nhãn gốc hoặc xác nhận model sai.
        limit/offset là trang ảnh đọc (mặc định 20); báo rõ tổng, lỗi và phân trang.
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
            candidates = request_false_carrier_candidates(payload)
            if candidates["status"] == "needs_drawing":
                if context:
                    candidates = {**candidates, "persistent_map": True,
                                  "message": "Vẽ/chọn vùng trên map rồi bấm Xác nhận trước khi kiểm tra."}
                    candidates.pop("map_url", None)
                return candidates
            if candidates["total"] == 0 or not candidates["ships"]:
                return {"status": "no_candidates" if candidates["total"] == 0 else "empty_page",
                        "total_candidates": candidates["total"], "filters": candidates["filters"],
                        "source_snapshot_id": candidates["source_snapshot_id"], "reviewed_count": 0,
                        "flags": [], "flagged_count": 0, "offset": offset, "limit": limit,
                        "coverage_complete": candidates["total"] == 0, "reference_comparison_performed": False}
            library = load_carrier_references()
        except (ValueError, httpx.HTTPError, OSError) as exc:
            raise ToolException("Chưa chuẩn bị được kiểm tra nhãn tàu sân bay; kiểm tra ngày/vùng, "
                                "file server và CARRIER_REFERENCE_DIR (mô tả cùng toàn bộ ảnh mẫu).") from exc
        from ship_agent.vision.image_review import _vision_model, review_image_against_references
        model = _vision_model()
        result = run_reference_reviews(candidates, library, lambda row, refs:
            review_image_against_references(row, refs, model=model), result_builder=build_false_carrier_evidence)
        result["investigation"] = "suspected_false_carriers"
        reviewed_ids = {item["observation_id"] for item in result["flags"] + result["unflagged"]}
        if reviewed_ids:
            result = attach_visual_input(result, [row for row in candidates["ships"]
                                                  if row["observation_id"] in reviewed_ids], library)
        if use_chat_area:
            result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
        return result

    return investigate_false_carriers
