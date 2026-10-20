"""Small spatial-query responses; map HTML never enters the model context."""

import os
import re
from urllib.parse import urlsplit

import httpx

from . import config


def _request_query(query: dict, *, data_source="file_server", transport=None, analysis=False):
    base = (os.environ.get("VESSELWATCH_DEMO_API_URL", "http://127.0.0.1:8002")
            if data_source == "demo" else config.FILE_SERVER_URL)
    with httpx.Client(base_url=base.rstrip("/") + "/", timeout=30, trust_env=False,
                      transport=transport) as client:
        response = client.post("observation-analyses" if analysis else "area-queries", json=query)
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
        collection = "pairs" if analysis and query.get("analysis") == "similar_dimensions" else "ships"
        if (type(result.get("total")) is not int or result["total"] < 0
                or not isinstance(result.get(collection), list)
                or len(result[collection]) > min(max(0, result["total"] - query.get("offset", 0)), query.get("limit", 20))):
            raise ValueError("Số liệu truy vấn vùng không hợp lệ.")
        if analysis and result.get("analysis") != query.get("analysis"):
            raise ValueError("Phản hồi không đúng loại phân tích được yêu cầu.")
    return result


def request_area_query(query: dict, *, data_source="file_server", transport=None):
    return _request_query(query, data_source=data_source, transport=transport)


def request_observation_analysis(query: dict, *, data_source="file_server", transport=None):
    return _request_query(query, data_source=data_source, transport=transport, analysis=True)
