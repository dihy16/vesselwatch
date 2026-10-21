"""The BR 17 tool preserves chat scope and sends only actually reviewed targets to chat vision."""

import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException

from file_server.carrier_references import load_reference_library
from ship_agent.carrier_investigation_tool import create_carrier_investigation_tool
from tests.agent.test_carrier_investigation_workflow import candidates
from tests.agent.test_false_carrier_evidence import visual
from tests.file_server.test_carrier_references import reference_folder, png
from tests.file_server.test_spatial import SQUARE


def setup_review(tmp_path, monkeypatch):
    from ship_agent import carrier_investigation_tool as module, image_review
    library = load_reference_library(reference_folder(tmp_path))
    monkeypatch.setattr(module, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "_vision_model", lambda: object())
    monkeypatch.setattr(image_review, "review_image_against_references", lambda row, refs, **kw: visual(row, refs))
    return module, library


def test_short_only_never_initializes_vision_or_reference_library(monkeypatch):
    from ship_agent import carrier_investigation_tool as module, image_review
    monkeypatch.setattr(module, "request_carrier_investigation_candidates", lambda _: candidates([100]))
    monkeypatch.setattr(module, "load_carrier_references", lambda: pytest.fail("Must not load library"))
    monkeypatch.setattr(image_review, "_vision_model", lambda: pytest.fail("Must not load vision"))
    result = create_carrier_investigation_tool().invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31"})
    assert result["priority_1_count"] == 1 and result["reviewed_count"] == 0 and "visual_input" not in result


def test_hidden_chat_polygon_and_only_reviewed_targets_in_direct_pixels(tmp_path, monkeypatch):
    module, library = setup_review(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(module, "request_carrier_investigation_candidates", lambda q: seen.append(q) or candidates([100, 300, None]))
    tool = create_carrier_investigation_tool()
    assert "config" not in tool.tool_call_schema.model_json_schema()["properties"]
    config = {"configurable": {"chat_area_context": {"user_id": "u", "chat_id": "c", "revision": 4, "active_area": SQUARE}}}
    result = tool.invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31", "use_chat_area": True}, config=config)
    assert seen[0]["polygon"] == SQUARE and result["chat_area_revision"] == 4
    assert result["priority_1_count"] == 1 and result["priority_2_count"] == 2
    assert result["visual_input"]["reference_revision"] == library.revision
    assert [target["observation_id"] for target in result["visual_input"]["targets"]] == ["1", "2"]
    config["configurable"]["chat_area_context"]["active_area"] = None
    with pytest.raises(ToolException):
        tool.invoke({"observed_from": "2025-01-01", "observed_to": "2025-12-31", "use_chat_area": True}, config=config)
    assert len(seen) == 1


def test_needs_drawing_on_persistent_map_returns_no_second_map(monkeypatch):
    from ship_agent import carrier_investigation_tool as module
    monkeypatch.setattr(module, "request_carrier_investigation_candidates", lambda _: {
        "status": "needs_drawing", "selection_id": "a" * 32, "map_url": "http://public/map"})
    config = {"configurable": {"chat_area_context": {"user_id": "u", "chat_id": "c", "active_area": None}}}
    result = create_carrier_investigation_tool().invoke({"observed_from": "2025-01-01",
        "observed_to": "2025-12-31", "area_name": "Hoàng Sa"}, config=config)
    assert result["status"] == "needs_drawing" and result["persistent_map"] and "map_url" not in result


def test_graph_receives_reviewed_pixels_only_and_priority_prompt(tmp_path, monkeypatch):
    from ship_agent.agent import build_agent
    from ship_agent import carrier_reference_client, image_review
    module, library = setup_review(tmp_path, monkeypatch)
    page = candidates([100, 300])
    monkeypatch.setattr(module, "request_carrier_investigation_candidates", lambda _: page)
    monkeypatch.setattr(carrier_reference_client, "load_carrier_references", lambda: library)
    seen_images = []
    def image_bytes(row, *args):
        seen_images.append(row["observation_id"])
        return png("green")
    monkeypatch.setattr(image_review, "_image_bytes", image_bytes)
    class Planner:
        calls = 0
        def bind_tools(self, tools):
            assert "investigate_carrier_detections" in {tool.name for tool in tools}
            return self
        def invoke(self, messages, **kwargs):
            self.calls += 1
            assert "priority=1 trước priority=2" in messages[0].content
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"id": "investigate", "name": "investigate_carrier_detections",
                    "args": {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}}])
            result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert [item["priority"] for item in result["flags"]] == [1, 2]
            assert sum(b["type"] == "image_url" for b in messages[-1].content) == 1 + len(library.images)
            return AIMessage(content="Ưu tiên 1: dài <300 m; ưu tiên 2: bằng chứng ảnh cần kiểm tra.")
    planner = Planner()
    state = build_agent(model=planner, observations=page["ships"]).invoke({"messages": [HumanMessage(
        content="Điều tra và xếp ưu tiên kiểm tra thủ công năm 2025.")]})
    assert seen_images == ["1"] and "<iframe" not in state["messages"][-1].text
