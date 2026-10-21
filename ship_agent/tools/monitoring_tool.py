"""BR 20: exact scoped/monthly monitoring plus reference evidence for selected positives."""

from typing import Literal

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool
from pydantic import Field

from file_server.schemas.monitoring import MonitoringScope, MonitoringRequest
from ship_agent.clients.carrier_reference_client import load_carrier_references
from ship_agent.clients.monitoring_client import request_monitoring_report
from ship_agent.runtime.chat_area import apply_chat_area, chat_area_context
from ship_agent.runtime.visual_context import attach_visual_input
from ship_agent.workflows.carrier_investigation import run_carrier_investigation


class MonitoringToolInput(MonitoringScope):
    use_chat_area: bool = Field(default=False, description="Dùng vùng đã xác nhận của chat.")
    output_format: Literal["html", "json"] = "html"


def create_monitoring_report_tool():
    @tool(args_schema=MonitoringToolInput)
    def vessel_monitoring_report(
        observed_from: str, observed_to: str, area_name: str | None = None, area_id: str | None = None,
        use_chat_area: bool = False, limit: int = 20, offset: int = 0,
        output_format: Literal["html", "json"] = "html", config: RunnableConfig = None,
    ) -> dict:
        """Câu 20: báo cáo giám sát theo vùng/ngày, so sánh tháng và kiểm tra chi tiết.

        Ngày bắt buộc; dùng vùng chat hoặc tên/mã vùng, bỏ vùng thì toàn nguồn.
        Thống kê TOÀN BỘ observations: ngày, dài/rộng, score và ba nhãn, kể cả
        unknown. So tháng dương lịch với tháng liền trước cùng vùng, ghi rõ
        số ngày truy vấn/tháng thiếu ngày, so trung bình lượt/ngày; baseline
        0 không tính % hoặc gọi tăng vô hạn. Chỉ mô tả lượt quan sát, không
        xác nhận hoạt động tàu tăng hay phát hiện bất thường có ý nghĩa thống kê.
        Kèm kiểm tra nhãn aircraft_carrier theo câu 17: <300 m ưu tiên 1 không
        đọc ảnh; còn lại đọc toàn bộ bộ mẫu, đủ rõ có bằng chứng nghi không
        phải tàu sân bay mới ưu tiên 2. Mờ/unknown không flag. limit/offset chỉ
        giới hạn trang kiểm tra, không cắt thống kê. Báo errors/coverage rõ.
        Mặc định html: hệ thống đính kèm báo cáo Artifacts, bạn viết nhận xét
        dựa số liệu/bằng chứng. json chỉ trả dữ liệu để trả lời trong chat.
        """
        try:
            scope = MonitoringScope(observed_from=observed_from, observed_to=observed_to,
                                    area_name=area_name, area_id=area_id, limit=limit, offset=offset)
            context = chat_area_context(config)
            payload = apply_chat_area(scope.model_dump(), config) if use_chat_area else scope.model_dump()
            payload = MonitoringRequest.model_validate(payload).model_dump()
        except ValueError as exc:
            raise ToolException(str(exc)) from exc
        try:
            report = request_monitoring_report(payload)
        except (ValueError, httpx.HTTPError, OSError) as exc:
            raise ToolException("Chưa lập được báo cáo giám sát; kiểm tra ngày/vùng và file server.") from exc
        if report["status"] == "needs_drawing":
            if context:
                report = {**report, "persistent_map": True,
                          "message": "Vẽ/chọn vùng trên map rồi bấm Xác nhận trước khi lập báo cáo."}
                report.pop("map_url", None)
            return report

        def create_reviewer():
            from ship_agent.vision.image_review import _vision_model, review_image_against_references
            model = _vision_model()
            return lambda row, refs: review_image_against_references(row, refs, model=model)

        review, library = run_carrier_investigation(report, load_library=load_carrier_references,
                                                   create_reviewer=create_reviewer)
        result = {key: report[key] for key in ("report_id", "report_kind", "source_snapshot_id", "statistics_filters",
                  "statistics", "monthly_stats", "comparison_policy", "unlocated_in_date_range_count", "missing_position_count")}
        result.update(status="complete", output_format=output_format, area_name=report.get("area_name"), review=review)
        reviewed_ids = {item["observation_id"] for item in review["flags"] + review["unflagged"]
                        if item["reference_comparison_performed"]}
        if reviewed_ids:
            result = attach_visual_input(result, [row for row in report["ships"] if row["observation_id"] in reviewed_ids], library)
        if use_chat_area:
            result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
        return result

    return vessel_monitoring_report
