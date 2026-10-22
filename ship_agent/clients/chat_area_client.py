"""Save a selected region through the trusted map API, with revision checks."""

import re
from urllib.parse import urlsplit

import httpx

from file_server.services.spatial import AREA_CENTERS, named_area, named_center, square_polygon
from file_server.storage.chat_areas import validate_active_area
from ship_agent import config


def selection_area(query):
    """Resolve only existing boundaries or the requested base/coordinate square."""
    if query.area_id:
        raise ValueError("Chọn vùng bằng tên có sẵn hoặc tâm/khoảng cách, không dùng mã vùng cũ.")
    if query.radius_nm is not None:
        center = AREA_CENTERS.get(named_center(query.area_name)) or {
            "latitude": query.center_latitude, "longitude": query.center_longitude}
        return square_polygon(center["latitude"], center["longitude"], query.radius_nm)
    key = named_area(query.area_name)
    if key:
        return {"type": "preset", "key": key}
    raise ValueError("Chọn Biển Đông/Vịnh Bắc Bộ hoặc hình vuông quanh căn cứ/tọa độ với khoảng cách hải lý; vùng khác cần tự vẽ.")


def selection_context(context):
    """Session credentials come from runtime, never model arguments or history."""
    if (not isinstance(context, dict) or context.get("error")
            or not context.get("user_id") or not context.get("chat_id")
            or not isinstance(context.get("session_id"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", context["session_id"])
            or type(context.get("revision")) is not int or context["revision"] < 0):
        raise ValueError("Chưa có phiên map hợp lệ của chat. Gửi 'mở bản đồ' từ Pipe hiện tại trước khi chọn vùng.")
    return context


def save_chat_area(context, area, *, transport=None):
    context = selection_context(context)
    area = validate_active_area(area)
    base = config.MAP_API_URL.rstrip("/") + "/"
    parts = urlsplit(base)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("MAP_API_URL của LangGraph không hợp lệ.")
    path = "map-sessions/" + context["session_id"]

    def validate(saved, revision):
        if (not isinstance(saved, dict)
                or any(saved.get(key) != context[key] for key in ("user_id", "chat_id", "session_id"))
                or type(saved.get("revision")) is not int or saved["revision"] != revision
                or "active_area" not in saved):
            raise ValueError("Phiên/vùng đã thay đổi; tải lại map và gửi lại yêu cầu chọn vùng.")
        validate_active_area(saved["active_area"])

    with httpx.Client(base_url=base, timeout=15, trust_env=False, transport=transport) as client:
        response = client.get(path)
        response.raise_for_status()
        validate(response.json(), context["revision"])
        response = client.put(path + "/area", json={"active_area": area, "expected_revision": context["revision"]})
        response.raise_for_status()
        saved = response.json()
        validate(saved, context["revision"] + 1)
        if saved["active_area"] != area:
            raise ValueError("Vùng lưu không khớp yêu cầu; tải lại vùng trên map để kiểm tra.")
    # Keep session credentials and API addresses out of tool outputs/checkpoints.
    return {"user_id": context["user_id"], "chat_id": context["chat_id"],
            "base_revision": context["revision"], "revision": saved["revision"], "active_area": area}
