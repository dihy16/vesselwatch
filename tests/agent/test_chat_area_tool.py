"""Runtime config injection into the actual spatial tool (requires LangGraph)."""

import pytest

import json
import httpx

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

import ship_agent.tools.areas as area_tools

from langchain_core.tools import ToolException
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from ship_agent.runtime.agent import build_agent
from ship_agent.tools.registry import create_tools
from tests.file_server.test_chat_areas import SQUARE


def test_tool_receives_hidden_chat_context_and_sends_polygon(monkeypatch):
    calls = []
    def query(payload, **kwargs):
        calls.append(payload)
        return {"status": "complete", "area_id": "a" * 32, "total": 4}
    monkeypatch.setattr(area_tools, "request_area_query", query)
    tool = next(t for t in create_tools(observations=[]) if t.name == "query_ships_in_area")
    assert "config" not in tool.tool_call_schema.model_json_schema()["properties"]
    config = {"configurable": {"thread_id": "chat-1", "chat_area_context": {
        "user_id": "u", "chat_id": "chat-1", "revision": 3, "active_area": SQUARE,
        "map_url": "http://viewer/map"}}}
    result = tool.invoke({"use_chat_area": True, "length_gt_m": 250}, config=config)
    assert calls[-1]["polygon"] == SQUARE and calls[-1]["length_gt_m"] == 250
    assert result["chat_area_revision"] == 3 and result["persistent_map"]
    assert "area_id" not in result
    config["configurable"]["chat_area_context"]["active_area"] = None
    with pytest.raises(ToolException):
        tool.invoke({"use_chat_area": True}, config=config)
    assert len(calls) == 1


def test_graph_passes_runtime_area_to_tool_without_model_coordinates_or_new_map(monkeypatch):
    payloads, requests = [], []
    def query(payload, **kwargs):
        payloads.append(payload)
        return {"status": "complete", "area_id": "a" * 32, "total": 2,
                "ships": [], "map_url": "http://unrelated/result"}
    monkeypatch.setattr(area_tools, "request_area_query", query)
    def model_response(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            assert "coordinates" not in json.dumps(body)
            assert "use_chat_area=true" in body["messages"][1]["content"]
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "current-area", "type": "function", "function": {
                    "name": "query_ships_in_area", "arguments": json.dumps({"use_chat_area": True})}}]}
        else:
            assert "private-map-session" not in json.dumps(body)
            message = {"role": "assistant", "content": "Có 2 lượt phát hiện trong vùng đã xác nhận."}
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
            "model": "test", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}]})
    config = {"configurable": {"thread_id": "chat-1", "chat_area_context": {
        "user_id": "u", "chat_id": "chat-1", "revision": 1, "active_area": SQUARE,
        "map_url": "http://viewer/map?map_session=private-map-session"}}}
    with httpx.Client(transport=httpx.MockTransport(model_response)) as client:
        model = ChatOpenAI(model="test", api_key="synthetic", http_client=client, max_retries=0)
        result = build_agent(model=model, observations=[]).invoke(
            {"messages": [HumanMessage(content="Đếm trong vùng vừa vẽ")]}, config=config)
    assert payloads[0]["polygon"] == SQUARE
    assert "<iframe" not in result["messages"][-1].text
