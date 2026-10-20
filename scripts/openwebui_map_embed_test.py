"""
title: VesselWatch Map Embed Test
description: Test a hosted map inline or in Artifacts using Open WebUI's iframe settings.
version: 0.3.0
"""

from html import escape
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        MAP_URL: str = Field(
            default="",
            description=(
                "URL map mở được từ trình duyệt đang dùng Open WebUI, "
                "ví dụ http://127.0.0.1:18000/demo/vessel_map.html"
            ),
        )
        MAP_HEIGHT_PX: int = Field(
            default=720,
            ge=320,
            le=1600,
            description="Chiều cao bản đồ trong tin nhắn, tính bằng pixel.",
        )
        DISPLAY_MODE: Literal["inline", "artifact"] = Field(
            default="inline",
            description=(
                "inline: bản đồ trong tin nhắn; artifact: HTML mở trong tab "
                "Artifacts bên cạnh chat."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    async def pipe(self, body: dict, __event_emitter__=None, __task__=None) -> str:
        # Background title/follow-up tasks must not publish another map embed.
        if __task__:
            return "VesselWatch Map Embed Test"

        content = next(
            (
                message.get("content", "")
                for message in reversed(body.get("messages", []))
                if message.get("role") == "user"
            ),
            "",
        )
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "")
                for block in content
                if block.get("type") == "text"
            )
        if not isinstance(content, str) or content.strip().casefold() != "map":
            return (
                "Đã nhận tin nhắn kiểm tra. Hãy quan sát map đang mở: "
                "zoom, bộ lọc và tàu đang chọn có giữ nguyên không? "
                "Gõ `map` nếu cần tạo một bản đồ nhúng mới. "
                "Đây là Pipe thử giao diện, chưa gọi agent."
            )

        url = self.valves.MAP_URL.strip()
        try:
            parsed = urlsplit(url)
            valid_url = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and not parsed.username
                and not parsed.password
            )
            parsed.port  # Reject malformed ports before sending HTML to the UI.
        except ValueError:
            valid_url = False
        if not valid_url:
            return "Hãy đặt MAP_URL trong Valves thành URL HTTP/HTTPS mở được từ trình duyệt."
        # Both inline embeds and Artifacts honor the user's same-origin setting.
        # This small wrapper supplies layout; the actual map is loaded by src.
        # No Leaflet code or observation data is copied into the chat message.
        height = self.valves.MAP_HEIGHT_PX
        is_artifact = self.valves.DISPLAY_MODE == "artifact"
        frame_height = "100vh" if is_artifact else f"{height}px"
        resize_script = "" if is_artifact else f"""<script>
    window.addEventListener("load", () => {{
      parent.postMessage({{type:"iframe:height",height:{height}}}, "*");
    }});
  </script>"""
        map_html = f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <title>Bản đồ tàu</title>
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <style>html,body{{margin:0;padding:0}}iframe{{display:block;width:100%;height:{frame_height};border:0}}</style>
</head>
<body>
  <iframe title="Bản đồ tàu" src="{escape(url, quote=True)}"
    height="{height}" referrerpolicy="strict-origin-when-cross-origin"
    sandbox="allow-scripts allow-same-origin allow-downloads"></iframe>
  {resize_script}
</body>
</html>"""
        if is_artifact:
            return (
                "Mở bản HTML này trong tab Artifacts bên cạnh chat. "
                "Bật Detect Artifacts Automatically nếu cần. "
                "Giữ map mở và gửi các tin nhắn khác chữ `map` để kiểm tra trạng thái."
                f"\n\n```html\n{map_html}\n```"
            )

        if __event_emitter__ is None:
            return "Hãy thử trong giao diện chat Open WebUI để nhận sự kiện mở map."
        await __event_emitter__(
            {
                "type": "embeds",
                "data": {"embeds": [map_html], "replace": True},
            }
        )
        return (
            "Bản đồ được nhúng ngay trong tin nhắn này. "
            "Nếu ảnh nền bị chặn, kiểm tra Settings → Interface → "
            "Iframe Sandbox Allow Scripts và Allow Same Origin đã bật. "
            "Thao tác trên map rồi gửi thêm vài tin nhắn khác chữ `map` "
            "để kiểm tra trạng thái."
        )
