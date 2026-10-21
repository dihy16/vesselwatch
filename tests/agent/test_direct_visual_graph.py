"""Verify the actual chat-provider request contains pixels and graph history does not."""

import base64
import json

import httpx
import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")
pytest.importorskip("langchain_openai")

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from file_server.carrier_references import load_reference_library
from ship_agent.agent import build_agent, _chat_visual_message
from tests.agent.test_pair_evidence import pair_rows, reviewed
from tests.file_server.test_carrier_references import png, reference_folder
from tests.integration.test_missed_carrier_client import response_payload


@pytest.mark.parametrize("mode", ["references", "single", "pair", "generic", "investigation", "false-investigation", "priority-investigation"])
def test_real_chat_serialization_has_targets_and_all_references_and_can_reopen(tmp_path, monkeypatch, mode):
    from ship_agent import carrier_reference_client, image_review, missed_carrier_tool, false_carrier_tool, carrier_investigation_tool
    from tests.integration.test_false_carrier_client import positive_payload
    from tests.agent.test_carrier_investigation_workflow import candidates
    from tests.agent.test_false_carrier_evidence import visual
    reference_folder(tmp_path)
    (tmp_path / "second.png").write_bytes(png("red"))
    library = load_reference_library(tmp_path)
    rows = list(pair_rows())
    if mode == "investigation":
        rows = response_payload()["ships"]
    elif mode == "false-investigation":
        rows = positive_payload()["ships"]
    elif mode == "priority-investigation":
        rows = candidates([100, 300])["ships"]
    for module in (carrier_reference_client, image_review, missed_carrier_tool, false_carrier_tool, carrier_investigation_tool):
        monkeypatch.setattr(module, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "_image_bytes", lambda row, *_: png("green" if row is rows[0] else "blue"))
    monkeypatch.setattr(image_review, "review_image_against_references", lambda row, refs, **kwargs:
        visual(row, refs) if mode == "priority-investigation" else
        reviewed(row, refs, "not_aircraft_carrier" if mode == "false-investigation" else "aircraft_carrier"))
    monkeypatch.setattr(image_review, "review_image", lambda row, **kwargs: {"observation_id": row["observation_id"]})
    monkeypatch.setattr(image_review, "_vision_model", lambda: object())
    monkeypatch.setattr(missed_carrier_tool, "request_missed_carrier_candidates", lambda _: response_payload())
    monkeypatch.setattr(false_carrier_tool, "request_false_carrier_candidates", lambda _: positive_payload())
    monkeypatch.setattr(carrier_investigation_tool, "request_carrier_investigation_candidates", lambda _: candidates([100, 300]))
    name, args = "review_ship_images", {"observation_id": rows[0]["observation_id"], "use_carrier_references": mode != "generic"}
    targets = rows[:1]
    if mode == "references":
        name, args, targets = "view_carrier_references", {}, []
    elif mode == "pair":
        args["comparison_observation_id"] = rows[1]["observation_id"]
        targets = rows
    elif mode == "investigation":
        name, args, targets = "investigate_missed_carriers", {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}, rows
    elif mode == "false-investigation":
        name, args, targets = "investigate_false_carriers", {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}, rows
    elif mode == "priority-investigation":
        name, args, targets = "investigate_carrier_detections", {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}, rows[1:]
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        image_blocks = [part for message in body["messages"] if isinstance(message.get("content"), list)
                        for part in message["content"] if part.get("type") == "image_url"]
        if len(requests) % 2:
            assert not image_blocks  # Follow-up must open images again, not reuse old base64.
            answer = {"role": "assistant", "content": None, "tool_calls": [{"id": "visual-" + str(len(requests)),
                "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
            finish = "tool_calls"
        else:
            actual = [base64.b64decode(part["image_url"]["url"].split(",", 1)[1]) for part in image_blocks]
            expected = [png("green" if row is rows[0] else "blue") for row in targets]
            assert actual == expected + ([] if mode == "generic" else [image.data for image in library.images])
            tool_result = next(m for m in reversed(body["messages"]) if m["role"] == "tool")
            assert "base64" not in tool_result["content"]
            if mode == "false-investigation":
                assert json.loads(tool_result["content"])["flagged_count"] == 1
            elif mode == "priority-investigation":
                result = json.loads(tool_result["content"])
                assert [item["priority"] for item in result["flags"]] == [1, 2]
                assert not result["flags"][0]["reference_comparison_performed"]
            answer, finish = {"role": "assistant", "content": "Đã xem trực tiếp ảnh trong lượt này."}, "stop"
        return httpx.Response(200, json={"id": "direct", "object": "chat.completion", "created": 0,
            "model": "chat-test", "choices": [{"index": 0, "finish_reason": finish, "message": answer}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="chat-test", api_key="test-only", http_client=client, max_retries=0)
        graph = build_agent(model=model, observations=rows)
        result = graph.invoke({"messages": [HumanMessage(content="Xem ảnh trực tiếp.")]})
        assert "data:image" not in json.dumps([m.model_dump() for m in result["messages"]])
        again = graph.invoke({"messages": [*result["messages"], HumanMessage(content="Xem lại các ảnh đó.")]})
    assert len(requests) == 4 and "data:image" not in json.dumps([m.model_dump() for m in again["messages"]])


def test_direct_image_failure_reports_no_pixels_without_leaking_error_body(monkeypatch):
    from ship_agent import carrier_reference_client
    def fail():
        raise ValueError("secret-provider-body")
    monkeypatch.setattr(carrier_reference_client, "load_carrier_references", fail)
    descriptor = {"targets": [], "reference_revision": "a" * 64}
    message = _chat_visual_message([HumanMessage(content="Xem mẫu"), ToolMessage(
        content=json.dumps({"visual_input": descriptor}), name="view_carrier_references", tool_call_id="refs")], [], "file_server")
    assert "direct_visual_context_unavailable" in message.content
    assert "secret-provider-body" not in message.content and "base64" not in message.content


def test_chat_model_rejecting_images_does_not_fall_back_to_text(tmp_path, monkeypatch):
    from ship_agent import carrier_reference_client, image_review
    library = load_reference_library(reference_folder(tmp_path))
    for module in (carrier_reference_client, image_review):
        monkeypatch.setattr(module, "load_carrier_references", lambda: library)
    class RejectImages:
        calls = 0
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"id": "refs", "name": "view_carrier_references", "args": {}}])
            assert any(isinstance(m.content, list) for m in messages)
            raise ValueError("secret-provider-image-body")
    model = RejectImages()
    with pytest.raises(RuntimeError, match="OPENAI_MODEL") as failure:
        build_agent(model=model, observations=[]).invoke({"messages": [HumanMessage(content="Mở bộ mẫu.")]})
    assert model.calls == 2 and "secret-provider-image-body" not in str(failure.value)
