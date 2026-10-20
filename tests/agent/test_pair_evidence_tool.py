"""Question 15 uses the existing image tool twice with exactly one reference snapshot."""

import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException

from file_server.carrier_references import load_reference_library
from ship_agent.image_review import create_image_review_tool
from tests.agent.test_pair_evidence import pair_rows, reviewed
from tests.file_server.test_carrier_references import png, reference_folder


def test_pair_uses_same_complete_library_for_both_images_once(tmp_path, monkeypatch):
    from ship_agent import image_review
    reference_folder(tmp_path)
    (tmp_path / "second.png").write_bytes(png("red"))
    library = load_reference_library(tmp_path)
    first, second = pair_rows()
    loaded, seen = [], []
    monkeypatch.setattr(image_review, "load_carrier_references", lambda: loaded.append(True) or library)
    def compare(row, refs, **kwargs):
        seen.append((row["observation_id"], refs))
        assert refs is library and len(refs.images) == 2
        return reviewed(row, refs, row["classification"])
    monkeypatch.setattr(image_review, "review_image_against_references", compare)
    tool = create_image_review_tool([first, second], data_source="file_server")
    result = tool.invoke({"observation_id": "positive", "comparison_observation_id": "negative",
                          "use_carrier_references": True})
    assert loaded == [True] and [identity for identity, _ in seen] == ["positive", "negative"]
    assert result["can_explain_label_difference"]
    assert result["first_observation"]["saved_prediction"]["classification"] == "aircraft_carrier"


def test_invalid_pair_does_not_load_references_or_call_vision(monkeypatch):
    from ship_agent import image_review
    first, second = pair_rows()
    second["width_m"] = 200
    monkeypatch.setattr(image_review, "load_carrier_references", lambda: pytest.fail("No library for invalid pair"))
    tool = create_image_review_tool([first, second], data_source="file_server")
    with pytest.raises(ToolException, match="vượt sai lệch"):
        tool.invoke({"observation_id": "positive", "comparison_observation_id": "negative", "use_carrier_references": True})
    with pytest.raises(ValueError):
        tool.invoke({"observation_id": "positive", "comparison_observation_id": "negative"})


def test_failed_second_image_does_not_create_a_fabricated_explanation(tmp_path, monkeypatch):
    from ship_agent import image_review
    library = load_reference_library(reference_folder(tmp_path))
    first, second = pair_rows()
    monkeypatch.setattr(image_review, "load_carrier_references", lambda: library)
    def compare(row, refs, **kwargs):
        if row["observation_id"] == "negative":
            raise ToolException("Second image failed")
        return reviewed(row, refs, "aircraft_carrier")
    monkeypatch.setattr(image_review, "review_image_against_references", compare)
    with pytest.raises(ToolException, match="Second image failed"):
        create_image_review_tool([first, second], data_source="file_server").invoke({
            "observation_id": "positive", "comparison_observation_id": "negative", "use_carrier_references": True})


def test_graph_selects_a_pair_then_compares_each_image_with_the_library(tmp_path, monkeypatch):
    from ship_agent import image_review, tools as module
    from ship_agent.agent import build_agent
    library = load_reference_library(reference_folder(tmp_path))
    first, second = pair_rows()
    monkeypatch.setattr(module, "request_observation_analysis", lambda query, **kwargs: {
        "status": "complete", "total": 100, "limit": 1, "offset": 0,
        "pairs": [{"aircraft_carrier": first, "not_aircraft_carrier": second}]})
    monkeypatch.setattr(image_review, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "review_image_against_references", lambda row, refs, **kwargs:
        reviewed(row, refs, row["classification"]))
    class Planner:
        calls = 0
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"id": "pair", "name": "analyze_ship_observations",
                    "args": {"analysis": "similar_dimensions", "limit": 1}}])
            if self.calls == 2:
                selected = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
                assert selected["total"] == 100
                return AIMessage(content="", tool_calls=[{"id": "review", "name": "review_ship_images",
                    "args": {"observation_id": "positive", "comparison_observation_id": "negative",
                             "use_carrier_references": True}}])
            result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert result["can_explain_label_difference"] and "base64" not in json.dumps(result)
            assert result["reference_revision"] == library.revision
            return AIMessage(content="Một cặp ví dụ: hai ảnh có đặc điểm đối chiếu bộ mẫu khác nhau.")
    planner = Planner()
    result = build_agent(model=planner, observations=[first, second]).invoke({"messages": [HumanMessage(
        content="Cho một ví dụ hai tàu kích thước tương đồng nhưng khác nhãn; đối chiếu bộ mẫu để giải thích.")]})
    assert planner.calls == 3 and "<iframe" not in result["messages"][-1].text
