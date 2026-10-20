"""Reference-pixel provider calls and real LangChain tool coordination, fully offline."""

import base64
import json

import httpx
import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException
from langchain_openai import ChatOpenAI

from file_server.carrier_references import load_reference_library
from ship_agent.image_review import review_image_against_references
from ship_agent.reference_review import reference_review_result
from ship_agent.missed_carrier_tool import create_missed_carrier_tool
from tests.file_server.test_carrier_references import png, reference_folder
from tests.integration.test_missed_carrier_client import response_payload
from tests.agent.test_reference_review import review
from tests.file_server.test_spatial import SQUARE


def test_actual_provider_receives_target_plus_every_reference_without_saved_scores(tmp_path):
    reference_folder(tmp_path)
    (tmp_path / "second.png").write_bytes(png("red"))
    library = load_reference_library(tmp_path)
    row = response_payload()["ships"][0]
    target = png("green")
    seen = []
    def respond(request):
        body = json.loads(request.content)
        seen.append(body)
        content = body["messages"][1]["content"]
        pixels = [base64.b64decode(item["image_url"]["url"].split(",", 1)[1])
                  for item in content if item["type"] == "image_url"]
        assert pixels == [target] + [image.data for image in library.images]
        assert row["ship_id"] not in json.dumps(body)
        assert "0.01" not in json.dumps(body)
        return httpx.Response(200, json={"id": "review", "object": "chat.completion", "created": 0,
            "model": "vision-test", "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": review(library).model_dump_json()}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="vision-test", api_key="test-only", http_client=client, max_retries=0)
        result = review_image_against_references(row, library, model=model,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=target)))
    assert len(seen) == 1 and result["flagged"] and "base64" not in json.dumps(result)


def test_tool_injects_area_reads_library_once_and_never_overwrites_label(tmp_path, monkeypatch):
    from ship_agent import missed_carrier_tool as module, image_review
    library = load_reference_library(reference_folder(tmp_path))
    seen, loaded = [], []
    monkeypatch.setattr(module, "request_missed_carrier_candidates", lambda payload:
        seen.append(payload) or response_payload())
    monkeypatch.setattr(module, "load_carrier_references", lambda: loaded.append(True) or library)
    monkeypatch.setattr(image_review, "_vision_model", lambda: object())
    monkeypatch.setattr(image_review, "review_image_against_references", lambda row, refs, **kwargs:
        reference_review_result(row, review(refs), refs))
    tool = create_missed_carrier_tool()
    assert "config" not in tool.tool_call_schema.model_json_schema()["properties"]
    config = {"configurable": {"thread_id": "c", "chat_area_context": {
        "user_id": "u", "chat_id": "c", "active_area": SQUARE, "revision": 4}}}
    result = tool.invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31",
                          "use_chat_area": True}, config=config)
    assert seen[0]["polygon"] == SQUARE and loaded == [True]
    assert result["flagged_count"] == 1 and result["chat_area_revision"] == 4
    assert result["flags"][0]["saved_prediction"]["classification"] == "not_aircraft_carrier"
    config["configurable"]["chat_area_context"]["active_area"] = None
    with pytest.raises(ToolException, match="Chưa có vùng"):
        tool.invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31",
                     "use_chat_area": True}, config=config)
    assert len(seen) == 1


def test_missing_references_fail_before_any_vision_request(monkeypatch):
    from ship_agent import missed_carrier_tool as module, image_review
    monkeypatch.setattr(module, "request_missed_carrier_candidates", lambda _: response_payload())
    def missing():
        raise ValueError("No examples")
    monkeypatch.setattr(module, "load_carrier_references", missing)
    monkeypatch.setattr(image_review, "_vision_model", lambda: pytest.fail("Must not call vision"))
    with pytest.raises(ToolException, match="CARRIER_REFERENCE_DIR"):
        create_missed_carrier_tool().invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31"})


def test_graph_uses_investigation_result_and_does_not_attach_a_second_map(tmp_path, monkeypatch):
    from ship_agent.agent import build_agent
    from ship_agent import missed_carrier_tool as module, image_review
    library = load_reference_library(reference_folder(tmp_path))
    monkeypatch.setattr(module, "request_missed_carrier_candidates", lambda _: response_payload())
    monkeypatch.setattr(module, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "_vision_model", lambda: object())
    monkeypatch.setattr(image_review, "review_image_against_references", lambda row, refs, **kwargs:
        reference_review_result(row, review(refs), refs))
    class Planner:
        calls = 0
        def bind_tools(self, tools):
            assert "investigate_missed_carriers" in {tool.name for tool in tools}
            return self
        def invoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"id": "investigate", "name": "investigate_missed_carriers",
                    "args": {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}}])
            result = json.loads(next(message.content for message in messages if isinstance(message, ToolMessage)))
            assert result["flagged_count"] == 1 and result["coverage_complete"]
            assert "base64" not in json.dumps(result)
            return AIMessage(content="Có 1 lượt phát hiện cần kiểm tra thủ công.")
    planner = Planner()
    result = build_agent(model=planner, observations=[]).invoke({"messages": [HumanMessage(
        content="Tìm tàu sân bay có thể bị bỏ sót từ 01/01/2025 đến 31/12/2025.")]})
    assert planner.calls == 2 and "<iframe" not in result["messages"][-1].text
