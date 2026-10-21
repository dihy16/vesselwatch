"""Question 13 reuses the actual image tool for arbitrary registered observations."""

import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException

from file_server.carrier_references import load_reference_library
from ship_agent.image_review import create_image_review_tool
from ship_agent.reference_review import reference_review_result
from tests.agent.test_reference_review import review
from tests.file_server.test_carrier_references import reference_folder
from tests.integration.test_missed_carrier_client import response_payload


def positive_observation():
    row = response_payload()["ships"][0]
    row.update(classification="aircraft_carrier", confidence=.99, length_m=220)
    return row


def test_reference_mode_accepts_positive_short_observation_and_preserves_default(tmp_path, monkeypatch):
    from ship_agent import image_review
    row = positive_observation()
    library = load_reference_library(reference_folder(tmp_path))
    loaded, compared = [], []
    monkeypatch.setattr(image_review, "load_carrier_references", lambda: loaded.append(True) or library)
    def compare(observation, refs, **kwargs):
        compared.append((observation, refs, kwargs))
        return reference_review_result(observation, review(refs), refs)
    monkeypatch.setattr(image_review, "review_image_against_references", compare)
    monkeypatch.setattr(image_review, "review_image", lambda observation, **_: {"legacy": observation["observation_id"]})
    tool = create_image_review_tool([row], data_source="file_server")
    generic = tool.invoke({"observation_id": "a"})
    assert generic["legacy"] == "a"
    assert generic["visual_input"]["reference_revision"] is None
    assert not loaded and not compared
    result = tool.invoke({"observation_id": "a", "use_carrier_references": True})
    assert result["review_mode"] == "carrier_reference_evidence"
    assert result["comparison"] == "agrees" and result["measured_dimensions"]["length_m"] == 220
    assert loaded == [True] and compared[0][0] is row
    assert compared[0][2]["data_source"] == "file_server"
    with pytest.raises(ToolException, match="Không tìm thấy"):
        tool.invoke({"observation_id": "not-registered", "use_carrier_references": True})
    assert len(loaded) == 1


def test_missing_references_never_falls_back_to_label_or_generic_review(monkeypatch):
    from ship_agent import image_review
    def missing():
        raise ValueError("No references")
    monkeypatch.setattr(image_review, "load_carrier_references", missing)
    monkeypatch.setattr(image_review, "review_image", lambda *_, **__: pytest.fail("No silent fallback"))
    monkeypatch.setattr(image_review, "review_image_against_references", lambda *_, **__: pytest.fail("No incomplete comparison"))
    with pytest.raises(ToolException, match="CARRIER_REFERENCE_DIR"):
        create_image_review_tool([positive_observation()], data_source="file_server").invoke(
            {"observation_id": "a", "use_carrier_references": True})


def test_graph_resolves_observation_then_reviews_evidence_without_candidate_screening(tmp_path, monkeypatch):
    from ship_agent import image_review
    from ship_agent.agent import build_agent
    row = positive_observation()
    library = load_reference_library(reference_folder(tmp_path))
    monkeypatch.setattr(image_review, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "review_image_against_references", lambda observation, refs, **kwargs:
        reference_review_result(observation, review(refs), refs))
    class Planner:
        calls = 0
        def bind_tools(self, tools):
            assert "use_carrier_references" in next(t for t in tools if t.name == "review_ship_images").args
            return self
        def invoke(self, messages, **kwargs):
            self.calls += 1
            assert "use_carrier_references=true" in messages[0].content
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"id": "find", "name": "search_ships",
                    "args": {"ship_id": row["ship_id"]}}])
            if self.calls == 2:
                found = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
                assert found["ships"][0]["observation_id"] == "a"
                return AIMessage(content="", tool_calls=[{"id": "review", "name": "review_ship_images",
                    "args": {"observation_id": "a", "use_carrier_references": True}}])
            result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert result["comparison"] == "agrees"
            assert {item["source"] for item in result["supporting_evidence"]} == {"image", "saved_prediction"}
            assert result["measured_dimensions"]["length_m"] == 220
            assert "flagged" not in result and "base64" not in json.dumps(result)
            return AIMessage(content="Ảnh có bằng chứng phù hợp bộ mẫu; chiều dài ghi nhận là 220 m.")
    planner = Planner()
    result = build_agent(model=planner, observations=[row]).invoke({"messages": [HumanMessage(
        content=f"Bằng chứng nào ủng hộ hoặc mâu thuẫn với nhận định {row['ship_id']} là tàu sân bay?")]})
    assert planner.calls == 3 and "220 m" in result["messages"][-1].text
    assert "<iframe" not in result["messages"][-1].text
