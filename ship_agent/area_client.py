"""Small spatial-query responses; map HTML never enters the model context."""

import os
import re
from urllib.parse import urlsplit

import httpx

from . import config


def request_area_query(query: dict, *, data_source="file_server", transport=None):
    base = (os.environ.get("VESSELWATCH_DEMO_API_URL", "http://127.0.0.1:8002")
            if data_source == "demo" else config.FILE_SERVER_URL)
    with httpx.Client(base_url=base.rstrip("/") + "/", timeout=30, trust_env=False,
                      transport=transport) as client:
        response = client.post("area-queries", json=query)
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict) or result.get("status") not in {"complete", "needs_drawing"}:
        raise ValueError("Phản hồi truy vấn vùng không hợp lệ.")
    key = "area_id" if result["status"] == "complete" else "selection_id"
    if not isinstance(result.get(key), str) or not re.fullmatch(r"[a-f0-9]{32}", result[key]):
        raise ValueError("Mã vùng không hợp lệ.")
    url = urlsplit(result.get("map_url", ""))
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        raise ValueError("URL bản đồ vùng không hợp lệ.")
    if result["status"] == "complete":
        if (type(result.get("total")) is not int or result["total"] < 0
                or not isinstance(result.get("ships"), list)
                or len(result["ships"]) > min(result["total"], query.get("limit", 20))):
            raise ValueError("Số liệu truy vấn vùng không hợp lệ.")
    return result
