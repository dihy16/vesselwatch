"""Image review and full reference-library tools."""

import httpx
from langchain_core.tools import ToolException, tool

from ship_agent import config
from ship_agent.clients.carrier_reference_client import load_carrier_references
from ship_agent.runtime.visual_context import attach_visual_input
from ship_agent.vision.observation_evidence import build_observation_evidence
from ship_agent.vision.pair_evidence import build_pair_evidence, validate_observation_pair
from ship_agent.vision.schemas import ReviewImageInput
import ship_agent.vision.image_review as image_review


def create_image_review_tool(observations, *, data_source):
    @tool(args_schema=ReviewImageInput)
    def review_ship_images(observation_id: str, use_carrier_references: bool = False,
                          comparison_observation_id: str | None = None, similarity_tolerance_pct: float = 10) -> dict:
        """Đọc nội dung ảnh thật để đánh giá bổ sung một lượt phát hiện tàu.

        Dùng khi yêu cầu phân tích ảnh, kiểm tra lại nhận dạng hoặc so sánh đặc điểm nhìn thấy.
        Lấy observation_id từ tool truy vấn trước; mỗi lần đọc ảnh đầu tiên của một observation.
        Trả đặc điểm nhìn thấy, chất lượng ảnh, hạn chế, nhận xét độc lập và đối chiếu prediction cũ.
        Không thay nhãn gốc; kết quả không phải nhãn xác nhận, unknown nếu không đủ rõ.
        Chỉ xem/hiển thị ảnh thì dùng URL từ search_ships, không cần gọi tool này.
        Với câu hỏi bằng chứng ủng hộ/mâu thuẫn tàu sân bay hoặc 'vì sao được nhận
        dạng', đặt use_carrier_references=true: đối chiếu TOÀN BỘ bộ mẫu, trả
        supporting_evidence/contradicting_evidence/unresolved, metadata kích thước
        và prediction. Không lọc theo nhãn, score, kích thước hoặc ngày của 14a.
        Mặc định false giữ đánh giá ảnh độc lập thông thường không cần bộ mẫu.
        Câu 15: thêm comparison_observation_id từ cặp similar_dimensions của câu 12,
        use_carrier_references=true và cùng similarity_tolerance_pct (mặc định 10%).
        Đọc riêng từng ảnh với CÙNG toàn bộ bộ mẫu, trả bằng chứng của cả hai ảnh.
        Không dùng bộ lọc 14a; không khẳng định hai ảnh là cùng một tàu hoặc biết
        nguyên nhân nội bộ classifier. Ảnh mờ/lỗi không tạo lời giải thích khác nhãn.
        """
        observation = next((row for row in observations if row["observation_id"] == observation_id), None)
        if observation is None:
            raise ToolException("Không tìm thấy observation_id; lấy ID chính xác từ tool truy vấn.")
        second = None
        if comparison_observation_id is not None:
            second = next((row for row in observations if row["observation_id"] == comparison_observation_id), None)
            if second is None:
                raise ToolException("Không tìm thấy comparison_observation_id; lấy ID chính xác từ cặp kết quả.")
            try:
                validate_observation_pair(observation, second, similarity_tolerance_pct)
            except ValueError as exc:
                raise ToolException(str(exc)) from exc
        if use_carrier_references:
            try:
                library = load_carrier_references()
            except (httpx.HTTPError, OSError, ValueError) as exc:
                raise ToolException("Chưa tải đủ bộ mẫu; kiểm tra CARRIER_REFERENCE_DIR, description.md và toàn bộ ảnh mẫu.") from exc
            reviewed = image_review.review_image_against_references(observation, library, data_source=data_source)
            if second is not None:
                second_reviewed = image_review.review_image_against_references(second, library, data_source=data_source)
                try:
                    result = build_pair_evidence(observation, second, reviewed, second_reviewed,
                                                 library, similarity_tolerance_pct)
                    return attach_visual_input(result, [observation, second], library)
                except ValueError as exc:
                    raise ToolException("Bằng chứng cặp ảnh không khớp observations hoặc cùng bộ mẫu; chưa so sánh được.") from exc
            try:
                result = build_observation_evidence(observation, reviewed, library)
                return attach_visual_input(result, [observation], library)
            except ValueError as exc:
                raise ToolException("Bằng chứng ảnh không khớp observation hoặc bộ mẫu; chưa tổng hợp được.") from exc
        return attach_visual_input(image_review.review_image(observation, data_source=data_source), [observation])

    return review_ship_images

def create_reference_view_tool():
    @tool
    def view_carrier_references() -> dict:
        """Mở toàn bộ ảnh mẫu tàu sân bay để LLM chat xem pixel và mô tả trực tiếp.

        Dùng khi hỏi xem/mô tả/so sánh lại bộ mẫu, ref1, ref2 hoặc ảnh tham chiếu.
        Không cần observation_id; không phân loại tàu hoặc tạo flag. Trả danh sách
        ID/tên cùng revision để hệ thống đưa TẤT CẢ ảnh mẫu vào lần gọi LLM kế tiếp.
        """
        try:
            library = load_carrier_references()
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise ToolException("Chưa mở được bộ mẫu; kiểm tra CARRIER_REFERENCE_DIR và file server.") from exc
        return attach_visual_input({"status": "ready", "reference_revision": library.revision,
            "reference_count": len(library.images), "reference_description": library.description,
            "reference_images": library.display_images(config.FILE_SERVER_URL)}, library=library)

    return view_carrier_references
