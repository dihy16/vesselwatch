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
from tests.file_server import test_chat_areas as chat_area_fixtures

session_server = chat_area_fixtures.session_server


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


@pytest.mark.parametrize("async_run", [False, True])
def test_selection_then_query_in_same_run_uses_new_area_without_exposing_artifact(session_server, monkeypatch, async_run):
    import asyncio
    from copy import deepcopy
    from ship_agent.clients.chat_area_client import selection_area
    from file_server.schemas.area_models import AreaQueryInput
    import ship_agent.config as settings

    base, store = session_server
    monkeypatch.setattr(settings, "MAP_API_URL", base)
    saved = store.ensure("u", "chat-1")
    runtime = {"configurable": {"thread_id": "chat-1", "chat_area_context": saved}}
    original = deepcopy(runtime)
    square = selection_area(AreaQueryInput(area_name="Du Lâm", radius_nm=20))
    payloads = []
    def backend(payload, **kwargs):
        payloads.append(payload)
        return {"status": "complete", "area_id": "a" * 32, "total": 2,
                "ships": [], "area_name": "Căn cứ Du Lâm ±20 hải lý (ô vuông)", "map_url": "http://viewer/map"}
    monkeypatch.setattr(area_tools, "request_area_query", backend)

    class Planner:
        calls = 0
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, **kwargs):
            from langchain_core.messages import AIMessage, ToolMessage
            self.calls += 1
            assert all(m.artifact is None for m in messages if isinstance(m, ToolMessage))
            assert saved["session_id"] not in str(messages)
            assert "coordinates" not in str(messages)
            if self.calls == 1:
                args = {"area_name": "Du Lâm", "radius_nm": 20, "set_as_chat_area": True}
            elif self.calls == 2:
                result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
                assert result["chat_area_selected"] and result["chat_area_revision"] == 1
                assert "Vùng đã xác nhận" in messages[1].content
                args = {"use_chat_area": True, "observed_from": "2025-01-01", "observed_to": "2025-12-31"}
            else:
                return AIMessage(content="Đã chọn hình vuông và truy vấn trong vùng mới.")
            return AIMessage(content="", tool_calls=[{"id": str(self.calls), "name": "query_ships_in_area", "args": args}])

    graph = build_agent(model=Planner(), observations=[])
    inputs = {"messages": [HumanMessage(content="Chọn vùng quanh Du Lâm 20 hải lý rồi đếm năm 2025.")]}
    result = asyncio.run(graph.ainvoke(inputs, config=runtime)) if async_run else graph.invoke(inputs, config=runtime)
    assert len(payloads) == 2 and payloads[1]["polygon"] == square
    assert store.get(saved["session_id"])["active_area"] == square
    assert runtime == original
    assert "<iframe" not in result["messages"][-1].text
    assert any(getattr(message, "artifact", None) for message in result["messages"])


def test_ordinary_named_query_does_not_save_or_modify_chat(monkeypatch):
    monkeypatch.setattr(area_tools, "request_area_query", lambda *args, **kwargs: {"status": "complete", "total": 0})
    monkeypatch.setattr(area_tools, "save_chat_area", lambda *args, **kwargs: pytest.fail("Read-only query must not save"))
    tool = next(t for t in create_tools(observations=[]) if t.name == "query_ships_in_area")
    result = tool.invoke({"area_name": "Du Lâm", "radius_nm": 20})
    assert "chat_area_selected" not in result


def test_failed_selection_does_not_claim_success_and_selection_requires_linked_chat(monkeypatch):
    from copy import deepcopy
    monkeypatch.setattr(area_tools, "request_area_query", lambda *args, **kwargs: {"status": "complete", "total": 0})
    def conflict(*args):
        raise ValueError("synthetic conflict")
    monkeypatch.setattr(area_tools, "save_chat_area", conflict)
    tool = next(t for t in create_tools(observations=[]) if t.name == "query_ships_in_area")
    args = {"area_name": "Du Lâm", "radius_nm": 20, "set_as_chat_area": True}
    with pytest.raises(ToolException):
        tool.invoke(args)
    runtime = {"configurable": {"thread_id": "c", "chat_area_context": {
        "user_id": "u", "chat_id": "c", "session_id": "a" * 64, "revision": 0, "active_area": None}}}
    before = deepcopy(runtime)
    with pytest.raises(ToolException):
        tool.invoke(args, config=runtime)
    assert runtime == before


def test_selection_artifact_is_scoped_to_current_turn():
    from ship_agent.runtime.attachments import config_with_selected_area
    from langchain_core.messages import ToolMessage
    runtime = {"configurable": {"chat_area_context": {"user_id": "u", "chat_id": "c", "revision": 0, "active_area": None}}}
    message = ToolMessage(name="query_ships_in_area", tool_call_id="select", content="{}", artifact={
        "chat_area_selection": {"user_id": "u", "chat_id": "c", "base_revision": 0, "revision": 1, "active_area": SQUARE}})
    turn = [HumanMessage(content="Chọn vùng"), message]
    assert config_with_selected_area(turn, runtime)["configurable"]["chat_area_context"]["active_area"] == SQUARE
    assert runtime["configurable"]["chat_area_context"]["active_area"] is None
    assert config_with_selected_area([*turn, HumanMessage(content="Câu hỏi mới")], runtime) == runtime


def test_parallel_selection_and_queries_are_rejected_before_any_side_effect(monkeypatch):
    from langchain_core.messages import AIMessage, ToolMessage
    monkeypatch.setattr(area_tools, "request_area_query", lambda *args, **kwargs: pytest.fail("No concurrent selection"))
    class Planner:
        calls = 0
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"id": "select", "name": "query_ships_in_area", "args": {
                        "area_name": "Du Lâm", "radius_nm": 20, "set_as_chat_area": True}},
                    {"id": "query", "name": "query_ships_in_area", "args": {"use_chat_area": True}}])
            assert sum(isinstance(m, ToolMessage) and m.status == "error" for m in messages) == 2
            return AIMessage(content="Cần chọn vùng trước.")
    build_agent(model=Planner(), observations=[]).invoke({"messages": [HumanMessage(content="Chọn rồi truy vấn")]})
