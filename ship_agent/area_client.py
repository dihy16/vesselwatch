"""Small spatial-query responses; map HTML never enters the model context."""

import os
import re
from urllib.parse import urlsplit

import httpx

from . import config


def _request_query(query: dict, *, data_source="file_server", transport=None, analysis=False, endpoint=None):
    base = (os.environ.get("VESSELWATCH_DEMO_API_URL", "http://127.0.0.1:8002")
            if data_source == "demo" else config.FILE_SERVER_URL)
    with httpx.Client(base_url=base.rstrip("/") + "/", timeout=30, trust_env=False,
                      transport=transport) as client:
        response = client.post(endpoint or ("observation-analyses" if analysis else "area-queries"), json=query)
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


def request_missed_carrier_candidates(query: dict, *, transport=None):
    from datetime import date, datetime, timedelta
    from math import isfinite
    from file_server.loader import Observation
    result = _request_query(query, transport=transport, endpoint="missed-carrier-candidates")
    if result["status"] != "complete":
        return result
    fingerprint = result.get("source_snapshot_id")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise ValueError("Missing candidate source snapshot.")
    expected = min(max(0, result["total"] - query.get("offset", 0)), query.get("limit", 20))
    if (len(result["ships"]) != expected or result.get("limit") != query.get("limit", 20)
            or result.get("offset") != query.get("offset", 0) or not isinstance(result.get("filters"), dict)):
        raise ValueError("Incomplete candidate page.")
    seen = set()
    for raw in result["ships"]:
        row = Observation.model_validate(raw).model_dump()
        day = date.fromisoformat(row["observed_date"])
        captured = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        if (day.isoformat() != row["observed_date"] or captured.tzinfo is None
                or captured.utcoffset() != timedelta(0) or captured.date() != day):
            raise ValueError("Candidate timestamps are not consistent UTC dates.")
        score, length = row["confidence"], row["length_m"]
        if (row["classification"] != "not_aircraft_carrier" or score is None
                or not isfinite(score) or score > .01 or length is None or length < 250
                or not query["observed_from"] <= row["observed_date"] <= query["observed_to"]
                or row["observation_id"] in seen):
            raise ValueError("Observation does not match the agreed missed-carrier filters.")
        seen.add(row["observation_id"])
    return result
