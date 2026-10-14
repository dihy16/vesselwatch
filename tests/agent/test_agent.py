"""Exercise actual ChatOpenAI serialization and LangGraph with no network."""

import json
from datetime import date

import httpx
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from ship_agent.agent import build_agent


def test_chatopenai_graph_executes_both_tools_and_returns_to_model():
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            assert {t["function"]["name"] for t in body["tools"]} == {"count_ships", "search_ships"}
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_count", "type": "function", "function": {
                    "name": "count_ships", "arguments": json.dumps({"observed_from": "2026-10-07", "observed_to": "2026-10-13"}),
                }},
                {"id": "call_search", "type": "function", "function": {
                    "name": "search_ships", "arguments": json.dumps({"ship_id": "SHIP_001"}),
                }},
            ]}
            reason = "tool_calls"
        else:
            results = {m["tool_call_id"]: json.loads(m["content"])
                       for m in body["messages"] if m["role"] == "tool"}
            assert results["call_count"]["daily_stats"][0]["suspicious_ship_count"] == 2
            assert results["call_search"]["ships"][0]["ship_id"] == "SHIP_001"
            message = {"role": "assistant", "content": "Kết quả từ hai tools là dữ liệu giả lập."}
            reason = "stop"
        return httpx.Response(200, json={
            "id": "chatcmpl-mock", "object": "chat.completion", "created": 0, "model": "gpt-4.1-mini",
            "choices": [{"index": 0, "message": message, "finish_reason": reason}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="gpt-4.1-mini", api_key="mock-key-not-real", http_client=client, max_retries=0)
        graph = build_agent(model=model, reference_date=date(2026, 10, 13), data_source="mock")
        result = graph.invoke({"messages": [HumanMessage(content="Thống kê 7 ngày qua và xem SHIP_001.")]})
    assert len(requests) == 2
    assert len([m for m in result["messages"] if isinstance(m, ToolMessage)]) == 2
    assert result["messages"][-1].content == "Kết quả từ hai tools là dữ liệu giả lập."


def test_graph_returns_invalid_tool_input_to_model_for_correction():
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_invalid", "type": "function", "function": {
                    "name": "search_ships", "arguments": '{"limit": 101}',
                },
            }]}
            reason = "tool_calls"
        else:
            errors = [m for m in body["messages"] if m["role"] == "tool"]
            assert len(errors) == 1 and "100" in errors[0]["content"]
            message = {"role": "assistant", "content": "Limit tối đa là 100."}
            reason = "stop"
        return httpx.Response(200, json={
            "id": "chatcmpl-mock", "object": "chat.completion", "created": 0, "model": "gpt-4.1-mini",
            "choices": [{"index": 0, "message": message, "finish_reason": reason}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="gpt-4.1-mini", api_key="mock-key-not-real", http_client=client, max_retries=0)
        result = build_agent(model=model, data_source="mock").invoke({"messages": [HumanMessage(content="Liệt kê tàu.")]})
    assert len(requests) == 2
    assert result["messages"][-1].content == "Limit tối đa là 100."


def test_default_real_agent_builds_without_fetching_and_reports_source_failure(monkeypatch):
    from ship_agent import tools as tools_module
    from ship_agent.file_server_client import FileServerError

    fetches = []
    requests = []

    def unavailable(first, last):
        fetches.append((first, last))
        raise FileServerError("Không kết nối được file server.")

    monkeypatch.setattr(tools_module, "load_observations", unavailable)

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        prompt = body["messages"][0]["content"]
        assert "múi giờ UTC" in prompt and "dữ liệu thật" in prompt
        assert "carrier score" in prompt
        assert "mọi quan sát, vị trí, phân loại và URL đều là dữ liệu giả lập" not in prompt
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_search", "type": "function", "function": {
                    "name": "search_ships", "arguments": "{}",
                },
            }]}
            reason = "tool_calls"
        else:
            errors = [m for m in body["messages"] if m["role"] == "tool"]
            assert len(errors) == 1 and "Không kết nối" in errors[0]["content"]
            message = {"role": "assistant", "content": "Chưa truy vấn được file server."}
            reason = "stop"
        return httpx.Response(200, json={
            "id": "chatcmpl-mock", "object": "chat.completion", "created": 0,
            "model": "gpt-4.1-mini",
            "choices": [{"index": 0, "message": message, "finish_reason": reason}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="gpt-4.1-mini", api_key="mock-key-not-real",
                           http_client=client, max_retries=0)
        graph = build_agent(model=model, reference_date=date(2026, 10, 13))
        assert fetches == []
        result = graph.invoke({"messages": [HumanMessage(content="Liệt kê tàu.")]})
    assert fetches == [(None, None)]
    assert len(requests) == 2
    assert result["messages"][-1].content == "Chưa truy vấn được file server."
