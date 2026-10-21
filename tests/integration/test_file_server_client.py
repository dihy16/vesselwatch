"""Validate paged API loading using HTTPX MockTransport; no live server."""

from datetime import date

import httpx
import pytest

from ship_agent.clients.file_server_client import FileServerError
from ship_agent.clients.file_server_client import load_observations


def observation(index, *, day="2026-10-13"):
    return {
        "observation_id": f"OBS_{index:03d}", "ship_id": f"SHIP_{index:03d}",
        "ship_url": f"http://127.0.0.1:8001/ships/SHIP_{index:03d}",
        "observed_date": day, "observed_at": f"{day}T23:00:00+00:00",
        "length_m": 300, "width_m": 60,
        "position": {"latitude": 12, "longitude": 112},
        "classification": "aircraft_carrier", "confidence": 0.75,
        "images": [{"image_id": f"IMG_{index:03d}",
                    "url": f"http://127.0.0.1:8001/images/IMG_{index:03d}",
                    "mime_type": "image/jpeg", "caption": "Ảnh Telegram"}],
    }


def page(rows, *, total=None, offset=0):
    return {"is_mock": False, "timezone": "UTC", "limit": 100, "offset": offset,
            "total": len(rows) if total is None else total, "observations": rows}


def test_all_pages_and_inclusive_date_parameters():
    rows = [observation(i) for i in range(205)]
    requests = []

    def respond(request):
        requests.append(request)
        offset = int(request.url.params["offset"])
        assert request.url.path == "/observations"
        assert request.url.params["limit"] == "100"
        assert request.url.params["observed_from"] == "2026-10-13"
        assert request.url.params["observed_to"] == "2026-10-13"
        assert request.extensions["timeout"]["read"] == 30.0
        return httpx.Response(200, json=page(rows[offset:offset + 100], total=205, offset=offset))

    loaded = load_observations(date(2026, 10, 13), date(2026, 10, 13),
                               transport=httpx.MockTransport(respond))
    assert loaded == rows
    assert [int(r.url.params["offset"]) for r in requests] == [0, 100, 200]


@pytest.mark.parametrize("first,last,expected", [
    (None, None, {}),
    (date(2026, 10, 13), None, {"observed_from": "2026-10-13"}),
    (None, date(2026, 10, 13), {"observed_to": "2026-10-13"}),
])
def test_empty_results_and_optional_date_boundaries(first, last, expected):
    def respond(request):
        assert dict(request.url.params) == {"limit": "100", "offset": "0", **expected}
        return httpx.Response(200, json=page([]))

    assert load_observations(first, last, transport=httpx.MockTransport(respond)) == []


@pytest.mark.parametrize("failure,message", [
    ("connect", "Không kết nối"), ("timeout", "30 giây"), ("status", "HTTP 503"),
])
def test_connection_timeout_and_status_report_errors(failure, message):
    def respond(request):
        if failure == "connect":
            raise httpx.ConnectError("offline", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(503)

    with pytest.raises(FileServerError, match=message):
        load_observations(transport=httpx.MockTransport(respond))


@pytest.mark.parametrize("problem", [
    "json", "schema", "missing_field", "score", "wrong_offset", "wrong_limit", "negative_total",
    "empty_before_total", "overflow", "mock", "timezone", "timestamp", "date", "day_mismatch",
    "non_utc", "outside_range", "repeated_id", "date_format",
])
def test_malformed_responses_do_not_turn_into_empty_results(problem):
    row = observation(0)
    document = page([row])
    if problem == "schema":
        document = []
    elif problem == "missing_field":
        del row["classification"]
    elif problem == "score":
        row["confidence"] = 2
    elif problem == "wrong_offset":
        document["offset"] = 100
    elif problem == "wrong_limit":
        document["limit"] = 20
    elif problem == "negative_total":
        document["total"] = -1
    elif problem == "empty_before_total":
        document["observations"] = []
    elif problem == "overflow":
        document["total"] = 0
    elif problem == "mock":
        document["is_mock"] = True
    elif problem == "timezone":
        document["timezone"] = "Asia/Ho_Chi_Minh"
    elif problem == "timestamp":
        row["observed_at"] = "broken"
    elif problem == "date":
        row["observed_date"] = "2026-02-30"
    elif problem == "date_format":
        row["observed_date"] = "20261013"
    elif problem == "day_mismatch":
        row["observed_at"] = "2026-10-12T23:00:00+00:00"
    elif problem == "non_utc":
        row["observed_at"] = "2026-10-13T23:00:00+07:00"
    elif problem == "outside_range":
        row.update(observed_date="2026-10-12", observed_at="2026-10-12T23:00:00Z")
    elif problem == "repeated_id":
        document = page([row, row])

    def respond(request):
        return (httpx.Response(200, text="broken JSON") if problem == "json"
                else httpx.Response(200, json=document))

    with pytest.raises(FileServerError, match="không hợp lệ hoặc thiếu trang"):
        load_observations(date(2026, 10, 13), transport=httpx.MockTransport(respond))


@pytest.mark.parametrize("problem", ["changed_total", "missing_page", "repeated_page"])
def test_second_page_failure_never_returns_partial_data(problem):
    rows = [observation(i) for i in range(100)]

    def respond(request):
        if request.url.params["offset"] == "0":
            return httpx.Response(200, json=page(rows, total=101))
        second = [observation(100)]
        if problem == "missing_page":
            second = []
        elif problem == "repeated_page":
            second = [rows[0]]
        total = 102 if problem == "changed_total" else 101
        return httpx.Response(200, json=page(second, total=total, offset=100))

    with pytest.raises(FileServerError):
        load_observations(transport=httpx.MockTransport(respond))


def test_separate_reads_see_new_data_and_configured_url(monkeypatch):
    from ship_agent import config

    monkeypatch.setattr(config, "FILE_SERVER_URL", "http://mid:8001")
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        assert request.url.host == "mid"
        return httpx.Response(200, json=page([observation(count)]))

    transport = httpx.MockTransport(respond)
    assert load_observations(transport=transport)[0]["observation_id"] == "OBS_001"
    assert load_observations(transport=transport)[0]["observation_id"] == "OBS_002"
