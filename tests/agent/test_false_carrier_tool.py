"""Positive-label auditing preserves scope, reviewed image inputs and honest coverage."""

import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException

from file_server.carrier_references import load_reference_library
from ship_agent.false_carrier_tool import create_false_carrier_tool
from tests.agent.test_false_carrier_evidence import visual
from tests.file_server.test_carrier_references import reference_folder, png
from tests.file_server.test_spatial import SQUARE
from tests.integration.test_false_carrier_client import positive_payload


def setup_review(tmp_path, monkeypatch):
    from ship_agent import false_carrier_tool as module, image_review
    library = load_reference_library(reference_folder(tmp_path))
    monkeypatch.setattr(module, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "_vision_model", lambda: object())
    monkeypatch.setattr(image_review, "review_image_against_references", lambda row, refs, **kwargs: visual(row, refs))
    return module, library


def test_hidden_chat_scope_and_full_pixel_descriptor_without_overwriting_prediction(tmp_path, monkeypatch):
    module, library = setup_review(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(module, "request_false_carrier_candidates", lambda query: seen.append(query) or positive_payload())
    tool = create_false_carrier_tool()
    assert "config" not in tool.tool_call_schema.model_json_schema()["properties"]
    config = {"configurable": {"chat_area_context": {"user_id": "u", "chat_id": "c", "revision": 4, "active_area": SQUARE}}}
    result = tool.invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31", "use_chat_area": True}, config=config)
    assert seen[0]["polygon"] == SQUARE and result["chat_area_revision"] == 4
    assert result["flagged_count"] == 1 and result["flags"][0]["saved_prediction"]["classification"] == "aircraft_carrier"
    assert result["visual_input"]["reference_revision"] == library.revision
    assert result["visual_input"]["targets"] == [{"observation_id": "a", "image_id": "image-a"}]
    config["configurable"]["chat_area_context"]["active_area"] = None
    with pytest.raises(ToolException):
        tool.invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31", "use_chat_area": True}, config=config)
    assert len(seen) == 1


@pytest.mark.parametrize("total,offset,status", [(0, 0, "no_candidates"), (1, 2, "empty_page")])
def test_empty_results_do_not_call_library_or_vision(monkeypatch, total, offset, status):
    from ship_agent import false_carrier_tool as module
    candidates = positive_payload()
    candidates.update(ships=[], total=total, offset=offset)
    monkeypatch.setattr(module, "request_false_carrier_candidates", lambda _: candidates)
    monkeypatch.setattr(module, "load_carrier_references", lambda: pytest.fail("No candidates to review"))
    result = create_false_carrier_tool().invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31", "offset": offset})
    assert result["status"] == status and not result["reference_comparison_performed"]
    assert result["coverage_complete"] is (total == 0)


def test_missing_library_and_all_failed_images_are_not_clean_negatives(tmp_path, monkeypatch):
    from ship_agent import false_carrier_tool as module, image_review
    monkeypatch.setattr(module, "request_false_carrier_candidates", lambda _: positive_payload())
    def missing():
        raise ValueError("No bank")
    monkeypatch.setattr(module, "load_carrier_references", missing)
    with pytest.raises(ToolException):
        create_false_carrier_tool().invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31"})
    setup_review(tmp_path, monkeypatch)
    def failed(*args, **kwargs):
        raise ValueError("secret-provider-body")
    monkeypatch.setattr(image_review, "review_image_against_references", failed)
    result = create_false_carrier_tool().invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31"})
    assert result["status"] == "failed" and result["failed_count"] == 1 and not result["coverage_complete"]
    assert "visual_input" not in result and "secret-provider-body" not in str(result)


def test_graph_receives_all_pixels_and_does_not_attach_another_map(tmp_path, monkeypatch):
    from ship_agent.agent import build_agent
    from ship_agent import carrier_reference_client, image_review
    module, library = setup_review(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "request_false_carrier_candidates", lambda _: positive_payload())
    monkeypatch.setattr(carrier_reference_client, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "_image_bytes", lambda *args: png("green"))
    class Planner:
        calls = 0
        def bind_tools(self, tools):
            assert "investigate_false_carriers" in {tool.name for tool in tools}
            return self
        def invoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"id": "audit", "name": "investigate_false_carriers",
                    "args": {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}}])
            result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert result["flagged_count"] == 1 and result["flags"][0]["flag_reason"] == "suspected_non_carrier"
            assert sum(b["type"] == "image_url" for b in messages[-1].content) == 1 + len(library.images)
            return AIMessage(content="Có 1 lượt phát hiện cần kiểm tra lại nhãn tàu sân bay.")
    planner = Planner()
    result = build_agent(model=planner, observations=positive_payload()["ships"]).invoke({"messages": [HumanMessage(
        content="Trong năm 2025, tìm ảnh dự đoán tàu sân bay nhưng có dấu hiệu không phải.")]})
    assert planner.calls == 2 and "<iframe" not in result["messages"][-1].text
