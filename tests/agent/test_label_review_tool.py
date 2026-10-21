"""BR 19 chat integration exposes group counts, annotation advice and all reviewed pixels."""

import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException

from file_server.carrier_references import load_reference_library
from ship_agent.label_review_tool import create_label_review_tool
from tests.agent.test_false_carrier_evidence import visual
from tests.file_server.test_carrier_references import reference_folder, png
from tests.file_server.test_spatial import SQUARE
from tests.integration.test_label_review_client import payload


QUERY = {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}


def setup(tmp_path, monkeypatch):
    from ship_agent import label_review_tool, image_review
    library = load_reference_library(reference_folder(tmp_path))
    monkeypatch.setattr(label_review_tool, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "_vision_model", lambda: object())
    monkeypatch.setattr(image_review, "review_image_against_references", lambda row, refs, **kw: visual(row, refs))
    return label_review_tool, library


def test_hidden_chat_scope_and_all_reviewed_targets_including_short_and_missing_score(tmp_path, monkeypatch):
    module, library = setup(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(module, "request_label_review_candidates", lambda q: seen.append(q) or payload())
    tool = create_label_review_tool()
    assert "config" not in tool.tool_call_schema.model_json_schema()["properties"]
    config = {"configurable": {"chat_area_context": {"user_id": "u", "chat_id": "c", "revision": 4, "active_area": SQUARE}}}
    result = tool.invoke({**QUERY, "use_chat_area": True}, config=config)
    assert seen[0]["polygon"] == SQUARE and result["chat_area_revision"] == 4
    assert result["group_counts"]["suspected_false_positive"] == 3
    assert result["annotation_candidate_count"] == 3
    assert [item["observation_id"] for item in result["visual_input"]["targets"]] == ["low", "high", "missing"]
    assert result["visual_input"]["reference_revision"] == library.revision
    config["configurable"]["chat_area_context"]["active_area"] = None
    with pytest.raises(ToolException):
        tool.invoke({**QUERY, "use_chat_area": True}, config=config)
    assert len(seen) == 1


def test_preparation_failure_preserves_metadata_and_has_no_stale_image_descriptor(monkeypatch):
    from ship_agent import label_review_tool
    monkeypatch.setattr(label_review_tool, "request_label_review_candidates", lambda _: payload())
    def missing():
        raise ValueError("private-provider-body")
    monkeypatch.setattr(label_review_tool, "load_carrier_references", missing)
    result = create_label_review_tool().invoke(QUERY)
    assert result["group_counts"]["review_failed"] == 3 and result["annotation_candidates"] == []
    assert result["candidate_statistics"]["detection_count"] == 3
    assert "visual_input" not in result and "private-provider-body" not in str(result)


def test_graph_receives_every_reviewed_target_and_group_evidence_without_new_map(tmp_path, monkeypatch):
    from ship_agent.agent import build_agent
    from ship_agent import carrier_reference_client, image_review
    module, library = setup(tmp_path, monkeypatch)
    page = payload()
    monkeypatch.setattr(module, "request_label_review_candidates", lambda _: page)
    monkeypatch.setattr(carrier_reference_client, "load_carrier_references", lambda: library)
    downloaded = []
    def pixels(row, *_):
        downloaded.append(row["observation_id"])
        return png("green")
    monkeypatch.setattr(image_review, "_image_bytes", pixels)
    class Planner:
        calls = 0
        def bind_tools(self, tools):
            assert "investigate_carrier_labels" in {item.name for item in tools}
            return self
        def invoke(self, messages, **kw):
            self.calls += 1
            assert "score thấp trước" in messages[0].content
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"id": "labels", "name": "investigate_carrier_labels", "args": QUERY}])
            result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert result["annotation_candidate_count"] == 3 and result["group_counts"]["review_failed"] == 0
            assert sum(part["type"] == "image_url" for part in messages[-1].content) == 3 + len(library.images)
            return AIMessage(content="Có ba lượt cần human xác minh nhãn, kèm bằng chứng đối chiếu.")
    model = Planner()
    state = build_agent(model=model, observations=page["ships"]).invoke({"messages": [HumanMessage(
        content="Điều tra nhãn tàu sân bay năm 2025, ưu tiên score thấp rồi đề xuất bổ sung nhãn.")]})
    assert downloaded == ["low", "high", "missing"] and "<iframe" not in state["messages"][-1].text
