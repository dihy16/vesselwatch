"""Agent spatial tools and drawing artifacts with mocked model/HTTP responses."""


import json

import httpx
import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

import ship_agent.tools.areas as area_tools

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from ship_agent.runtime.attachments import _current_maps
from ship_agent.runtime.agent import build_agent
from ship_agent.tools.registry import create_tools


def test_unknown_area_tool_result_attaches_drawing_map(monkeypatch):

    calls = []

    def query(arguments, *, data_source):
        calls.append((arguments, data_source))
        return {"status": "needs_drawing", "selection_id": "a" * 32,
                "map_url": "http://viewer:8001/area-queries/" + "a" * 32}

    monkeypatch.setattr(area_tools, "request_area_query", query)
    requests = []

    def model_response(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            assert "query_ships_in_area" in {t["function"]["name"] for t in body["tools"]}
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "area", "type": "function", "function": {"name": "query_ships_in_area",
                    "arguments": json.dumps({"area_name": "Hoàng Sa", "length_gt_m": 250})}}]}
        else:
            message = {"role": "assistant", "content": "Hãy vẽ vùng trên bản đồ rồi bấm xác nhận."}
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
            "model": "test", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}]})

    with httpx.Client(transport=httpx.MockTransport(model_response)) as client:
        model = ChatOpenAI(model="test", api_key="synthetic", http_client=client, max_retries=0)
        graph = build_agent(model=model, observations=[])
        result = graph.invoke({"messages": [HumanMessage(content="Tìm tàu dài trên 250 m ở Hoàng Sa.")]})
    assert calls[0][0]["area_name"] == "Hoàng Sa" and calls[0][0]["length_gt_m"] == 250
    assert "<iframe" in result["messages"][-1].text
    assert "0 lượt" not in result["messages"][-1].text


def test_named_correction_removes_previous_unconfirmed_selection():
    messages = [HumanMessage(content="Trong Vịnh Bắc Bộ"),
                ToolMessage(name="query_ships_in_area", tool_call_id="first", content=json.dumps({
                    "status": "needs_drawing", "selection_id": "a" * 32, "map_url": "http://viewer/map"})),
                ToolMessage(name="query_ships_in_area", tool_call_id="second", content=json.dumps({
                    "status": "complete", "area_id": "b" * 32, "total": 3}))]
    assert _current_maps(messages) == []


def test_area_tool_preserves_confirmed_reference_and_strict_dimensions(monkeypatch):

    captured = []
    monkeypatch.setattr(area_tools, "request_area_query", lambda query, **kwargs: captured.append(query) or {"total": 2})
    tool = next(t for t in create_tools(observations=[]) if t.name == "query_ships_in_area")
    tool.invoke({"area_id": "a" * 32, "observed_from": "2026-10-01", "observed_to": "2026-10-02",
                 "length_gt_m": 250, "classification": "aircraft_carrier"})
    assert captured[0]["area_id"] == "a" * 32 and captured[0]["length_gt_m"] == 250
    assert captured[0]["classification"] == "aircraft_carrier"
