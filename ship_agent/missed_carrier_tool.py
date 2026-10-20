"""Coordinate candidate filtering, complete reference loading and pixel comparisons."""

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool
from pydantic import Field

from file_server.missed_carriers import MissedCarrierScope, MissedCarrierRequest
from .area_client import request_missed_carrier_candidates
from .carrier_reference_client import load_carrier_references
from .chat_area import apply_chat_area, chat_area_context
from .reference_review import run_reference_reviews


class MissedCarrierToolInput(MissedCarrierScope):
    use_chat_area: bool = Field(default=False,
        description="Dùng vùng đã xác nhận của chat; bỏ area_name và area_id. Không có vùng thì lọc toàn nguồn theo ngày.")


def create_missed_carrier_tool():
    @tool(args_schema=MissedCarrierToolInput)
    def investigate_missed_carriers(
        observed_from: str, observed_to: str, area_name: str | None = None, area_id: str | None = None,
        use_chat_area: bool = False, limit: int = 20, offset: int = 0,
        config: RunnableConfig = None,
    ) -> dict:
        """Tìm ảnh có thể bị bỏ sót tàu sân bay rồi đọc ảnh đối chiếu toàn bộ bộ mẫu.

        Bắt buộc khoảng ngày YYYY-MM-DD. Vùng tùy chọn; use_chat_area=true cho vùng chat.
        Lọc nhãn not_aircraft_carrier, carrier score <=0.01 và chiều dài >=250 m,
        sau đó so TARGET với mô tả và TẤT CẢ ảnh mẫu do người dùng cung cấp.
        Chỉ flag khi ảnh đủ rõ và có đặc điểm phù hợp bộ mẫu; ảnh mờ không flag.
        Không thay prediction, không xác nhận ground truth hay danh tính cùng tàu.
        limit/offset phân trang các ứng viên được đọc ảnh (mặc định 20), không phân trang
        trước khi lọc. Báo số đã đọc/tổng ứng viên, lỗi, ảnh mờ và next_offset;
        không coi một trang hay các lỗi đọc ảnh là kết quả đầy đủ của toàn khu vực.
        """
        try:
            scope = MissedCarrierScope(observed_from=observed_from, observed_to=observed_to,
                                       area_name=area_name, area_id=area_id, limit=limit, offset=offset)
            context = chat_area_context(config)
            payload = apply_chat_area(scope.model_dump(), config) if use_chat_area else scope.model_dump()
            payload = MissedCarrierRequest.model_validate(payload).model_dump()
        except ValueError as exc:
            raise ToolException(str(exc)) from exc
        try:
            candidates = request_missed_carrier_candidates(payload)
            if candidates["status"] == "needs_drawing":
                result = candidates
                if context:
                    result = {**result, "persistent_map": True,
                              "message": "Vẽ/chọn vùng trên map rồi bấm Xác nhận trước khi đối chiếu."}
                    result.pop("map_url", None)
                return result
            if candidates["total"] == 0 or not candidates["ships"]:
                return {"status": "no_candidates" if candidates["total"] == 0 else "empty_page",
                        "total_candidates": candidates["total"], "filters": candidates["filters"],
                        "source_snapshot_id": candidates["source_snapshot_id"], "reviewed_count": 0,
                        "flags": [], "flagged_count": 0, "offset": offset, "limit": limit,
                        "coverage_complete": candidates["total"] == 0, "reference_comparison_performed": False}
            library = load_carrier_references()
        except (ValueError, httpx.HTTPError, OSError) as exc:
            raise ToolException("Chưa chuẩn bị được đối chiếu: kiểm tra khoảng ngày/vùng, data server và "
                                "CARRIER_REFERENCE_DIR (description.md cùng toàn bộ ảnh mẫu hợp lệ).") from exc
        from .image_review import _vision_model, review_image_against_references
        model = _vision_model()
        result = run_reference_reviews(candidates, library, lambda row, refs:
            review_image_against_references(row, refs, model=model))
        if use_chat_area:
            result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
        return result

    return investigate_missed_carriers
