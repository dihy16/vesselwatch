"""The main model gets exact counts, only reviewed pixels and a deterministic report artifact."""

import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException

from file_server.media.carrier_references import load_reference_library
from ship_agent.tools.monitoring_tool import create_monitoring_report_tool
from tests.agent.test_false_carrier_evidence import visual
from tests.file_server.test_carrier_references import reference_folder, png
from tests.file_server.test_spatial import SQUARE
from tests.integration.test_monitoring_client import payload


QUERY = {"observed_from": "2025-01-01", "observed_to": "2025-02-28"}


def setup(tmp_path, monkeypatch):
    import ship_agent.tools.monitoring_tool as monitoring_tool
    import ship_agent.vision.image_review as image_review
    library = load_reference_library(reference_folder(tmp_path))
    monkeypatch.setattr(monitoring_tool, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "_vision_model", lambda: object())
    monkeypatch.setattr(image_review, "review_image_against_references", lambda row, refs, **kw: visual(row, refs))
    return monitoring_tool, library


def test_hidden_chat_area_same_snapshot_counts_and_only_reviewed_target_pixels(tmp_path, monkeypatch):
    module, library = setup(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(module, "request_monitoring_report", lambda query: seen.append(query) or payload())
    tool = create_monitoring_report_tool()
    assert "config" not in tool.tool_call_schema.model_json_schema()["properties"]
    config = {"configurable": {"chat_area_context": {"user_id": "u", "chat_id": "c", "revision": 4, "active_area": SQUARE}}}
    result = tool.invoke({**QUERY, "use_chat_area": True}, config=config)
    assert seen[0]["polygon"] == SQUARE and result["chat_area_revision"] == 4
    assert result["statistics"]["detection_count"] == 4 and result["review"]["total_candidates"] == 2
    assert result["review"]["priority_1_count"] == result["review"]["priority_2_count"] == 1
    assert [row["observation_id"] for row in result["visual_input"]["targets"]] == ["long"]
    assert result["visual_input"]["reference_revision"] == library.revision
    config["configurable"]["chat_area_context"]["active_area"] = None
    with pytest.raises(ToolException):
        tool.invoke({**QUERY, "use_chat_area": True}, config=config)
    assert len(seen) == 1


def test_unavailable_library_preserves_monthly_report_and_dimension_results(monkeypatch):
    import ship_agent.tools.monitoring_tool as monitoring_tool
    monkeypatch.setattr(monitoring_tool, "request_monitoring_report", lambda _: payload())
    def unavailable():
        raise ValueError("private-error-body")
    monkeypatch.setattr(monitoring_tool, "load_carrier_references", unavailable)
    result = create_monitoring_report_tool().invoke(QUERY)
    assert result["statistics"]["detection_count"] == 4 and result["review"]["priority_1_count"] == 1
    assert result["review"]["failed_count"] == 1 and "visual_input" not in result
    assert "private-error-body" not in str(result)


@pytest.mark.parametrize("output_format", ["html", "json"])
def test_graph_attaches_only_requested_report_and_reloads_reviewed_pixels(tmp_path, monkeypatch, output_format):
    from ship_agent.runtime.agent import build_agent
    import ship_agent.clients.carrier_reference_client as carrier_reference_client
    import ship_agent.vision.image_review as image_review
    module, library = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "request_monitoring_report", lambda _: payload())
    monkeypatch.setattr(carrier_reference_client, "load_carrier_references", lambda: library)
    seen = []
    def pixels(row, *_):
        seen.append(row["observation_id"])
        return png("green")
    monkeypatch.setattr(image_review, "_image_bytes", pixels)
    class Planner:
        calls = 0
        def bind_tools(self, tools):
            assert "vessel_monitoring_report" in {item.name for item in tools}
            return self
        def invoke(self, messages, **kw):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"id": "report", "name": "vessel_monitoring_report",
                    "args": {**QUERY, "output_format": output_format}}])
            report = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert report["statistics"]["detection_count"] == 4
            assert sum(part["type"] == "image_url" for part in messages[-1].content) == 1 + len(library.images)
            return AIMessage(content="Đã tổng hợp số liệu theo tháng và bằng chứng cần kiểm tra.")
    model = Planner()
    state = build_agent(model=model, observations=payload()["ships"]).invoke({"messages": [HumanMessage(content="Lập báo cáo giám sát và so theo tháng.")]})
    answer = state["messages"][-1].text
    assert ("<!DOCTYPE html>" in answer) == (output_format == "html")
    assert "<iframe" not in answer and seen == ["long"]
