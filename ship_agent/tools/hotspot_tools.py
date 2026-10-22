"""BR 18 geographic discovery followed by exact-membership reference investigation."""

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool
from pydantic import Field

from file_server.schemas.reviews import (
    HotspotClusterScope,
    HotspotClusterRequest,
    FalseCarrierRequest,
    FalseCarrierScope,
)
from ship_agent.clients.carrier_reference_client import load_carrier_references
from ship_agent.clients.hotspot_client import request_carrier_hotspots, request_carrier_hotspot_candidates
from ship_agent.runtime.chat_area import apply_chat_area, chat_area_context
from ship_agent.runtime.visual_context import attach_visual_input
from ship_agent.tools.schemas import FalseCarrierToolInput
from ship_agent.workflows.carrier_investigation import run_carrier_investigation


class HotspotReviewInput(HotspotClusterScope):
    use_chat_area: bool = Field(default=False, description="Dùng đúng vùng chat đã xác nhận khi tìm cụm.")


def _scope_payload(scope, config, use_chat_area, request_type):
    context = chat_area_context(config)
    payload = apply_chat_area(scope.model_dump(), config) if use_chat_area else scope.model_dump()
    return context, request_type.model_validate(payload).model_dump()


def _drawing(result, context):
    if context:
        result = {**result, "persistent_map": True,
                  "message": "Vẽ/chọn vùng trên map rồi bấm Xác nhận trước khi tìm cụm."}
        result.pop("map_url", None)
    return result


def create_carrier_hotspot_tools():
    @tool(args_schema=FalseCarrierToolInput)
    def find_carrier_hotspots(
        observed_from: str, observed_to: str, area_name: str | None = None, area_id: str | None = None,
        center_latitude: float | None = None, center_longitude: float | None = None, radius_nm: float | None = None,
        use_chat_area: bool = False, limit: int = 20, offset: int = 0, config: RunnableConfig = None,
    ) -> dict:
        """Câu 18: tìm cụm nhiều lượt nghi tàu sân bay và phân tích phân bố.

        Ngày bắt buộc, vùng tùy chọn; không có vùng thì tìm toàn nguồn. Lọc nhãn
        aircraft_carrier rồi DBSCAN toàn bộ tọa độ bằng Haversine, eps=30 km,
        min_samples=2 (tính cả điểm đang xét), không phân trang observations trước.
        Cụm xếp theo số lượt giảm dần; limit/offset phân trang CỤM. Trả phân bố
        vị trí, từng ngày, dài/rộng và score; báo riêng điểm lẻ noise/thiếu tọa độ.
        Đây là lượt quan sát, không phải số tàu hoặc mật độ hoạt động thực tế.
        Chọn cụm từ kết quả và gọi investigate_carrier_hotspot với report_id,
        cluster_id, cùng ngày/vùng để kiểm tra theo quy tắc câu 17.
        """
        try:
            scope = FalseCarrierScope(observed_from=observed_from, observed_to=observed_to,
                                      center_latitude=center_latitude, center_longitude=center_longitude, radius_nm=radius_nm,
                                      area_name=area_name, area_id=area_id, limit=limit, offset=offset)
            context, payload = _scope_payload(scope, config, use_chat_area, FalseCarrierRequest)
            result = request_carrier_hotspots(payload)
        except (ValueError, httpx.HTTPError, OSError) as exc:
            raise ToolException("Chưa tìm được cụm; kiểm tra ngày/vùng, file server và dependency scikit-learn.") from exc
        if result["status"] == "needs_drawing":
            return _drawing(result, context)
        if use_chat_area:
            result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
        return result

    @tool(args_schema=HotspotReviewInput)
    def investigate_carrier_hotspot(
        observed_from: str, observed_to: str, report_id: str, cluster_id: str,
        area_name: str | None = None, area_id: str | None = None, use_chat_area: bool = False,
        center_latitude: float | None = None, center_longitude: float | None = None, radius_nm: float | None = None,
        limit: int = 20, offset: int = 0, config: RunnableConfig = None,
    ) -> dict:
        """Câu 18: kiểm tra chi tiết đúng các observations thuộc cụm đã tìm.

        Dùng report_id/cluster_id từ find_carrier_hotspots, cùng ngày/vùng.
        Không tự vẽ polygon bao cụm hoặc suy ra tọa độ từ tên. Backend kiểm tra
        snapshot/phạm vi; thay đổi thì tìm cụm lại. limit/offset là trang LƯỢT
        trong cụm, sau khi sắp nhóm <300 m trước toàn bộ nhóm còn lại.
        Áp dụng câu 17: ưu tiên 1 dài <300 m không đọc ảnh; phần còn lại đọc
        toàn bộ bộ mẫu, đủ rõ có bằng chứng nghi không phải tàu sân bay mới
        vào ưu tiên 2. Mờ/unknown không flag, lỗi báo riêng. Không đổi nhãn gốc.
        """
        try:
            scope = HotspotClusterScope(observed_from=observed_from, observed_to=observed_to,
                report_id=report_id, cluster_id=cluster_id, area_name=area_name, area_id=area_id,
                center_latitude=center_latitude, center_longitude=center_longitude, radius_nm=radius_nm,
                limit=limit, offset=offset)
            context, payload = _scope_payload(scope, config, use_chat_area, HotspotClusterRequest)
            candidates = request_carrier_hotspot_candidates(payload)
        except (ValueError, httpx.HTTPError, OSError) as exc:
            raise ToolException("Chưa lấy được thành viên cụm; giữ đúng ngày/vùng và tìm cụm lại nếu nguồn đã đổi.") from exc
        if candidates["status"] == "needs_drawing":
            return _drawing(candidates, context)

        def create_reviewer():
            from ship_agent.vision.image_review import _vision_model, review_image_against_references
            model = _vision_model()
            return lambda row, refs: review_image_against_references(row, refs, model=model)

        result, library = run_carrier_investigation(candidates, load_library=load_carrier_references,
                                                   create_reviewer=create_reviewer)
        result.update(investigation="carrier_hotspot_manual_review", report_id=report_id, cluster_id=cluster_id)
        reviewed_ids = {item["observation_id"] for item in result["flags"] + result["unflagged"]
                        if item["reference_comparison_performed"]}
        if reviewed_ids:
            result = attach_visual_input(result, [row for row in candidates["ships"]
                                                  if row["observation_id"] in reviewed_ids], library)
        if use_chat_area:
            result.update(query_scope="chat_active_area", chat_area_revision=context["revision"])
        return result

    return [find_carrier_hotspots, investigate_carrier_hotspot]
