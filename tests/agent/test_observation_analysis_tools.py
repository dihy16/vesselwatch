"""Real tool schemas, strict counts, and chat-area injection without LLM calls."""

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.tools import ToolException
from ship_agent.tools import create_tools
from file_server.area_models import ObservationAnalysisRequest
from file_server.observation_analysis import analyze_observations
from file_server.spatial import AreaGeometry
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def test_search_score_and_length_strict_full_counts():
    rows = [row("a"), row("b"), row("exact-score", score=.8), row("exact-length", length=250),
            row("negative", label="not_aircraft_carrier"), row("unknown-score", score=None)]
    tools = {t.name: t for t in create_tools(observations=rows)}
    result = tools["search_ships"].invoke({"length_gt_m": 250, "carrier_score_gt": .8,
                                         "classification": "aircraft_carrier", "limit": 1})
    assert result["total"] == 2 and len(result["ships"]) == 1


def test_analysis_tool_uses_full_backend_and_hidden_chat_polygon(monkeypatch):
    from ship_agent import tools as module
    rows = [row("p"), row("n", label="not_aircraft_carrier"), row("outside", x=115)]
    received = []
    def analyze(payload, **kwargs):
        received.append(payload)
        request = ObservationAnalysisRequest.model_validate(payload)
        return {"status": "complete", "area_id": "a" * 32, "map_url": "http://private-map",
                **analyze_observations(rows, request, AreaGeometry(payload["polygon"]))}
    monkeypatch.setattr(module, "request_observation_analysis", analyze)
    tool = next(t for t in create_tools(observations=rows) if t.name == "analyze_ship_observations")
    assert "config" not in tool.tool_call_schema.model_json_schema()["properties"]
    config = {"configurable": {"thread_id": "c", "chat_area_context": {
        "user_id": "u", "chat_id": "c", "revision": 2, "active_area": SQUARE}}}
    for mode in ("dimension_mismatch", "similar_dimensions"):
        result = tool.invoke({"analysis": mode, "use_chat_area": True}, config=config)
        assert result["total"] == 1 and result["chat_area_revision"] == 2
        assert "map_url" not in result and "area_id" not in result
        assert received[-1]["polygon"] == SQUARE
    config["configurable"]["chat_area_context"]["active_area"] = None
    with pytest.raises(ToolException):
        tool.invoke({"analysis": "similar_dimensions", "use_chat_area": True}, config=config)
    assert len(received) == 2
