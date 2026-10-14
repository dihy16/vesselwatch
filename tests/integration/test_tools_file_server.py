"""Real-source tools use fake paged HTTP responses, with no network or LLM."""

from datetime import date
import importlib
import sys

import httpx
import pytest

pytest.importorskip("langchain_core")

from ship_agent import tools as tools_module
from ship_agent.file_server_client import FileServerError, load_observations


def row(index):
    return {
        "observation_id": f"OBS_{index:03d}", "ship_id": f"SHIP_{index:03d}",
        "ship_url": "http://127.0.0.1:8001/ships/example",
        "observed_date": "2026-10-13", "observed_at": "2026-10-13T23:00:00+00:00",
        "length_m": 300 if index >= 100 else 180, "width_m": 60,
        "position": {"latitude": 12, "longitude": 112},
        "classification": "aircraft_carrier", "confidence": 0.8,
        "images": [],
    }


def test_import_makes_no_http_requests(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("HTTP must not run during tools module import")

    monkeypatch.setattr(httpx.Client, "get", fail)
    importlib.reload(tools_module)


def test_full_pagination_count_and_filter_before_search_pagination(monkeypatch):
    rows = [row(i) for i in range(105)]
    requests = []

    def respond(request):
        requests.append(request)
        assert "observed_from" not in request.url.params
        assert "observed_to" not in request.url.params
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json={
            "is_mock": False, "timezone": "UTC", "total": len(rows), "limit": 100,
            "offset": offset, "observations": rows[offset:offset + 100],
        })

    def fetch():
        return load_observations(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(tools_module, "load_observations", fetch)
    count, search = tools_module.create_tools(date(2026, 10, 14))
    assert [r.url.params["offset"] for r in requests] == ["0", "100"]
    dates = {"observed_from": "2026-10-13", "observed_to": "2026-10-13"}
    result = search.invoke({**dates, "min_length_m": 250, "limit": 2, "offset": 1})
    assert result["total"] == 5
    assert [r["ship_id"] for r in result["ships"]] == ["SHIP_101", "SHIP_102"]
    assert result["reference_date"] == "2026-10-14"
    assert result["timezone"] == "UTC" and result["is_mock"] is False
    stats = count.invoke(dates)["daily_stats"]
    assert stats == [{"date": "2026-10-13", "suspicious_ship_count": 105,
                      "possible_aircraft_carrier_count": 105}]
    assert search.invoke({"observed_from": "2026-10-14"})["total"] == 0
    assert [r.url.params["offset"] for r in requests] == ["0", "100"]


def test_source_failure_stops_creation(monkeypatch):
    def fail(*args):
        raise FileServerError("Không kết nối được file server.")

    monkeypatch.setattr(tools_module, "load_observations", fail)
    with pytest.raises(FileServerError, match="file server"):
        tools_module.create_tools()


def test_graph_entry_point_preloads_once_for_multiple_runs(monkeypatch):
    from ship_agent import agent, file_server_client

    rows = [row(0)]
    fetches, snapshots = [], []

    def fetch():
        fetches.append(True)
        return rows

    def build(**kwargs):
        snapshots.append(kwargs["observations"])
        return object()

    monkeypatch.setattr(file_server_client, "load_observations", fetch)
    monkeypatch.setattr(agent, "build_agent", build)
    monkeypatch.delitem(sys.modules, "ship_agent.graph", raising=False)
    module = importlib.import_module("ship_agent.graph")
    try:
        assert fetches == [True]
        module.make_graph({})
        module.make_graph({})
        assert fetches == [True]
        assert len(snapshots) == 2 and all(snapshot is rows for snapshot in snapshots)
    finally:
        sys.modules.pop("ship_agent.graph", None)


def test_same_caption_ship_id_keeps_separate_images_in_tools(monkeypatch):
    rows = [{**row(i), "ship_id": "SAME_DETECTION"} for i in range(2)]
    rows[1]["classification"] = "not_aircraft_carrier"
    monkeypatch.setattr(tools_module, "load_observations", lambda: rows)
    count, search = tools_module.create_tools()
    result = search.invoke({"ship_id": "SAME_DETECTION"})
    assert result["total"] == 2
    assert {o["observation_id"] for o in result["ships"]} == {"OBS_000", "OBS_001"}
    assert search.invoke({"classification": "aircraft_carrier"})["total"] == 1
    stats = count.invoke({"observed_from": "2026-10-13", "observed_to": "2026-10-13"})
    assert stats["daily_stats"] == [{"date": "2026-10-13", "suspicious_ship_count": 2,
                                     "possible_aircraft_carrier_count": 1}]


def test_empty_date_range_returns_zero_counts(monkeypatch):
    monkeypatch.setattr(tools_module, "load_observations", lambda: [])
    count, search = tools_module.create_tools()
    result = count.invoke({"observed_from": "2026-10-13", "observed_to": "2026-10-14"})
    assert [s["suspicious_ship_count"] for s in result["daily_stats"]] == [0, 0]
    assert search.invoke({})["total"] == 0


def test_mock_mode_never_uses_file_server(monkeypatch):
    def fail(*args):
        raise AssertionError("Mock mode must not use file server")

    monkeypatch.setattr(tools_module, "load_observations", fail)
    _, search = tools_module.create_tools(date(2026, 10, 13), data_source="mock")
    assert search.invoke({})["is_mock"] is True
    with pytest.raises(ValueError, match="data_source"):
        tools_module.create_tools(data_source="typo")
