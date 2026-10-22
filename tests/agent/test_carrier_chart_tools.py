"""Mock HTTP/LLM checks for carrier report tools and HTML Artifacts output."""

from datetime import date
import json
from urllib.parse import urlencode

import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException
from langchain_openai import ChatOpenAI
import pytest

from file_server.services.carrier_reports import daily_carrier_report
from ship_agent.runtime.agent import build_agent
from ship_agent.clients.file_server_client import FileServerError
from ship_agent.clients.file_server_client import load_daily_carrier_report
from ship_agent.artifacts.report_artifacts import render_carrier_artifact
import ship_agent.tools.registry as tools_module

import ship_agent.tools.reports as reports_tools


FIRST, LAST = date(2026, 10, 12), date(2026, 10, 14)


def report_data():
    report = daily_carrier_report([
        {"observation_id": "one", "observed_date": FIRST.isoformat(),
         "classification": "aircraft_carrier"},
    ], FIRST, LAST)
    query = urlencode({"observed_from": report["observed_from"],
                       "observed_to": report["observed_to"], "report_id": report["report_id"]})
    return {**report, "is_mock": False, "chart_url": f"http://viewer:8001/charts/daily-carriers.png?{query}",
            "coverage": {"observation_count": 1, "skipped": {"missing_prediction": 0}}}


def test_client_requests_full_range_and_keeps_public_chart_url():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=report_data())

    report = load_daily_carrier_report(FIRST, LAST, base_url="http://internal:8001",
                                     transport=httpx.MockTransport(respond))
    assert str(requests[0].url).startswith("http://internal:8001/reports/daily-carriers?")
    assert requests[0].url.params["observed_to"] == LAST.isoformat()
    assert report["chart_url"].startswith("http://viewer:8001/")
    assert report["total_detections"] == 1


@pytest.mark.parametrize("change", ["missing_day", "total", "negative", "url", "range", "json"])
def test_client_rejects_inconsistent_report_data(change):
    report = report_data()
    if change == "missing_day":
        report["daily_stats"].pop()
    elif change == "total":
        report["total_detections"] = 99
    elif change == "negative":
        report["daily_stats"][0]["possible_aircraft_carrier_count"] = -1
    elif change == "url":
        report["chart_url"] = "javascript:alert(1)"
    elif change == "range":
        report["observed_from"] = "2026-10-11"

    def respond(request):
        return httpx.Response(200, text="invalid JSON") if change == "json" else httpx.Response(200, json=report)

    with pytest.raises(FileServerError, match="không hợp lệ"):
        load_daily_carrier_report(FIRST, LAST, transport=httpx.MockTransport(respond))


@pytest.mark.parametrize("output_format", ["html", "png"])
def test_tool_returns_server_authoritative_report_and_handles_failures(monkeypatch, output_format):
    def fetch(first, last):
        assert first == FIRST and last == LAST
        return report_data()

    monkeypatch.setattr(reports_tools, "load_daily_carrier_report", fetch)
    tool = tools_module.create_tools(date(2026, 10, 14), observations=[])[2]
    arguments = {"observed_from": FIRST.isoformat(), "observed_to": LAST.isoformat(),
                 "output_format": output_format}
    result = tool.invoke(arguments)
    # Deliberately empty initial agent snapshot: report/PNG use server data together.
    assert result["total_detections"] == 1
    assert result["reference_date"] == "2026-10-14"
    assert result["output_format"] == output_format
    assert result["chart_url"] == report_data()["chart_url"]

    def fail(*args):
        raise FileServerError("Không kết nối được file server.")

    monkeypatch.setattr(reports_tools, "load_daily_carrier_report", fail)
    with pytest.raises(ToolException, match="file server"):
        tool.invoke(arguments)


def test_mock_report_makes_no_http_and_does_not_invent_chart_url(monkeypatch):
    monkeypatch.setattr(reports_tools, "load_daily_carrier_report",
                        lambda *args: pytest.fail("Mock must not call real file server"))
    tool = tools_module.create_tools(date(2026, 10, 14), data_source="mock")[2]
    report = tool.invoke({"observed_from": FIRST.isoformat(), "observed_to": LAST.isoformat()})
    assert report["is_mock"] is True and report["chart_url"] is None
    assert report["total_detections"] == sum(
        s["possible_aircraft_carrier_count"] for s in report["daily_stats"]
    )
    with pytest.raises(ToolException, match="mock"):
        tool.invoke({"observed_from": FIRST.isoformat(), "observed_to": LAST.isoformat(),
                     "output_format": "png"})


@pytest.mark.parametrize("stream", [False, True])
def test_graph_report_round_trip_returns_html_artifact(monkeypatch, stream):
    monkeypatch.setattr(reports_tools, "load_daily_carrier_report", lambda *args: report_data())
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert "daily_carrier_report" in body["messages"][0]["content"]
        assert "code block html" in body["messages"][0]["content"]
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_report", "type": "function", "function": {
                    "name": "daily_carrier_report", "arguments": json.dumps({
                        "observed_from": FIRST.isoformat(), "observed_to": LAST.isoformat(),
                    }),
                },
            }]}
            reason = "tool_calls"
        else:
            result = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "tool"))
            assert result["total_detections"] == 1
            assert "<!DOCTYPE html>" not in json.dumps(result)
            message = {"role": "assistant", "content": "1 lượt dự đoán."}
            reason = "stop"
        if body.get("stream"):
            delta = {**message}
            if delta.get("tool_calls"):
                delta["tool_calls"] = [
                    {"index": i, **call} for i, call in enumerate(delta["tool_calls"])
                ]
            chunks = [
                {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 0,
                 "model": "test", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 0,
                 "model": "test", "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]},
            ]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
                "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            ).encode())
        return httpx.Response(200, json={
            "id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "message": message, "finish_reason": reason}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="test", api_key="synthetic", http_client=client, max_retries=0)
        graph = build_agent(model=model, observations=[])
        inputs = {
            "messages": [HumanMessage(content="Vẽ biểu đồ tàu sân bay từ 12 đến 14/10/2026.")],
        }
        if stream:
            events = list(graph.stream(inputs, stream_mode="messages"))
            answers = [m for m, _ in events
                       if isinstance(m, AIMessage) and not m.tool_calls and m.content]
            assert len(answers) == 1
            answer = answers[0].content
        else:
            answer = graph.invoke(inputs)["messages"][-1].content
    assert len(requests) == 2
    assert answer == f"1 lượt dự đoán.\n\n```html\n{render_carrier_artifact(report_data())}\n```"
    assert report_data()["chart_url"] not in answer


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("output_format", ["html", "png"])
def test_graph_never_reuses_previous_turn_artifact_after_followup_or_error(failure, output_format):
    history = [
        HumanMessage(content="Báo cáo trước."),
        AIMessage(content="", tool_calls=[{
            "id": "old_report", "name": "daily_carrier_report", "args": {},
        }]),
        ToolMessage(content=json.dumps({**report_data(), "output_format": output_format}), name="daily_carrier_report",
                    tool_call_id="old_report"),
        AIMessage(content="Báo cáo cũ.\n```html\n<html></html>\n```"),
        HumanMessage(content="Câu hỏi mới."),
    ]
    if failure:
        history.extend([
            AIMessage(content="", tool_calls=[{
                "id": "failed_report", "name": "daily_carrier_report", "args": {},
            }]),
            ToolMessage(content="Không kết nối được file server.", name="daily_carrier_report",
                        tool_call_id="failed_report", status="error"),
        ])

    def respond(request):
        return httpx.Response(200, json={
            "id": "chatcmpl-followup", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Nhận xét mới."},
                         "finish_reason": "stop"}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="test", api_key="synthetic", http_client=client, max_retries=0)
        result = build_agent(model=model, observations=[]).invoke({"messages": history})
    assert result["messages"][-1].content == "Nhận xét mới."
