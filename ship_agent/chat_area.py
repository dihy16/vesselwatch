"""Resolve a per-run chat-area snapshot without exposing coordinates to the LLM."""

from copy import deepcopy

from file_server.chat_areas import validate_active_area
from file_server.spatial import AREA_NAMES


def chat_area_context(config):
    configurable = (config or {}).get("configurable", {})
    context = configurable.get("chat_area_context")
    if context is None:
        return None
    if not isinstance(context, dict):
        raise ValueError("Ngữ cảnh vùng chat không hợp lệ.")
    if not context.get("chat_id") or not context.get("user_id"):
        raise ValueError("Ngữ cảnh vùng thiếu định danh cuộc chat.")
    if configurable.get("thread_id") not in (None, context["chat_id"]):
        raise ValueError("Vùng không thuộc thread hiện tại.")
    return context


def apply_chat_area(query, config):
    context = chat_area_context(config)
    if context is None:
        raise ValueError("Chưa liên kết map với cuộc chat này. Hãy mở map từ cùng Pipe.")
    if context.get("error"):
        raise ValueError("Chưa đọc được vùng chat. Kiểm tra server map; không dùng vùng của lượt trước.")
    if query.get("area_name") or query.get("area_id"):
        raise ValueError("Chỉ dùng vùng đang chọn hoặc một vùng chỉ định; không truy vấn nhiều vùng.")
    area = validate_active_area(context.get("active_area"))
    if area is None:
        raise ValueError("Chưa có vùng được xác nhận. Hãy vẽ/chọn vùng trên map rồi bấm Xác nhận.")
    result = deepcopy(query)
    if area["type"] == "preset":
        result["area_name"] = AREA_NAMES[area["key"]]
    else:
        result["polygon"] = area
    return result


def chat_area_note(config):
    try:
        context = chat_area_context(config)
        if context is None:
            return ""
        if context.get("error"):
            state = "Chưa đọc được vùng do lỗi server map; không dùng vùng hay kết quả cũ."
        else:
            area = validate_active_area(context.get("active_area"))
            state = ("Chưa có vùng được xác nhận; yêu cầu vẽ/chọn và Xác nhận trên map."
                     if area is None else
                     "Vùng đã xác nhận: " + (AREA_NAMES[area["key"]] if area["type"] == "preset"
                                              else "polygon tùy ý trên map"))
    except ValueError:
        state = "Ngữ cảnh vùng không hợp lệ; không được dùng kết quả cũ."
    return (
        "VÙNG CỦA CUỘC CHAT Ở LƯỢT HIỆN TẠI: " + state + "\n"
        "Khi người dùng hỏi 'vùng này', 'vùng vừa vẽ', 'vùng đang chọn' hoặc tiếp tục "
        "câu hỏi về vùng đã chọn, gọi tool phù hợp (query_ships_in_area hoặc "
        "analyze_ship_observations) với use_chat_area=true, "
        "bỏ area_name và area_id. Không lấy mã vùng cũ từ lịch sử. "
        "Chỉ xử lý một vùng mỗi truy vấn; nếu yêu cầu nhiều vùng hãy yêu cầu chọn một. "
        "Nếu hỏi rõ một khu vực khác, dùng area_name theo quy tắc vùng định nghĩa sẵn/tự vẽ. "
        "Không tạo map mới cho câu hỏi tiếp nối: người dùng đã có map trong Artifacts."
    )
