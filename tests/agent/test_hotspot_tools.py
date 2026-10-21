"""Discovery/review orchestration keeps chat polygons, report IDs and visual scope intact."""

import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException

from file_server.media.carrier_references import load_reference_library
from ship_agent.tools.hotspot_tools import create_carrier_hotspot_tools
from tests.agent.test_carrier_investigation_workflow import candidates
from tests.agent.test_false_carrier_evidence import visual
from tests.file_server.test_carrier_references import reference_folder, png
from tests.file_server.test_spatial import SQUARE


QUERY = {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}
REVIEW = {**QUERY, "report_id": "a" * 64, "cluster_id": "b" * 32}


def setup_review(tmp_path, monkeypatch):
    import ship_agent.tools.hotspot_tools as hotspot_tools
    import ship_agent.vision.image_review as image_review
    library = load_reference_library(reference_folder(tmp_path))
    monkeypatch.setattr(hotspot_tools, "load_carrier_references", lambda: library)
    monkeypatch.setattr(image_review, "_vision_model", lambda: object())
    monkeypatch.setattr(image_review, "review_image_against_references", lambda row, refs, **kw: visual(row, refs))
    return hotspot_tools, library


def test_discovery_and_review_share_exact_hidden_chat_scope(tmp_path, monkeypatch):
    module, library = setup_review(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(module, "request_carrier_hotspots", lambda q: seen.append(q) or {"status": "complete"})
    monkeypatch.setattr(module, "request_carrier_hotspot_candidates", lambda q: seen.append(q) or candidates([100, 300, None]))
    find, investigate = create_carrier_hotspot_tools()
    for tool in (find, investigate):
        assert "config" not in tool.tool_call_schema.model_json_schema()["properties"]
    config = {"configurable": {"chat_area_context": {"user_id": "u", "chat_id": "c", "revision": 4, "active_area": SQUARE}}}
    discovery = find.invoke({**QUERY, "use_chat_area": True}, config=config)
    result = investigate.invoke({**REVIEW, "use_chat_area": True}, config=config)
    assert seen[0]["polygon"] == seen[1]["polygon"] == SQUARE
    assert discovery["chat_area_revision"] == result["chat_area_revision"] == 4
    assert result["report_id"] == REVIEW["report_id"] and result["cluster_id"] == REVIEW["cluster_id"]
    assert result["priority_1_count"] == 1 and result["priority_2_count"] == 2
    assert [item["observation_id"] for item in result["visual_input"]["targets"]] == ["1", "2"]
    assert result["visual_input"]["reference_revision"] == library.revision
    config["configurable"]["chat_area_context"]["active_area"] = None
    with pytest.raises(ToolException):
        investigate.invoke({**REVIEW, "use_chat_area": True}, config=config)
    assert len(seen) == 2


def test_short_members_need_no_vision_and_empty_clusters_need_no_references(monkeypatch):
    import ship_agent.tools.hotspot_tools as hotspot_tools
    monkeypatch.setattr(hotspot_tools, "load_carrier_references", lambda: pytest.fail("No image review expected"))
    monkeypatch.setattr(hotspot_tools, "request_carrier_hotspot_candidates", lambda _: candidates([100]))
    _, investigate = create_carrier_hotspot_tools()
    result = investigate.invoke(REVIEW)
    assert result["priority_1_count"] == 1 and "visual_input" not in result
    monkeypatch.setattr(hotspot_tools, "request_carrier_hotspots", lambda _: {"status": "complete", "total": 0})
    assert create_carrier_hotspot_tools()[0].invoke(QUERY)["total"] == 0


def test_drawing_reuses_persistent_panel_and_backend_errors_do_not_become_empty_results(monkeypatch):
    import ship_agent.tools.hotspot_tools as hotspot_tools
    monkeypatch.setattr(hotspot_tools, "request_carrier_hotspots", lambda _: {
        "status": "needs_drawing", "selection_id": "c" * 32, "map_url": "http://public/map"})
    config = {"configurable": {"chat_area_context": {"user_id": "u", "chat_id": "c", "active_area": None}}}
    find, investigate = create_carrier_hotspot_tools()
    result = find.invoke({**QUERY, "area_name": "Hoàng Sa"}, config=config)
    assert result["persistent_map"] and "map_url" not in result
    def stale(_):
        raise ValueError("private-provider-body")
    monkeypatch.setattr(hotspot_tools, "request_carrier_hotspot_candidates", stale)
    with pytest.raises(ToolException) as error:
        investigate.invoke(REVIEW)
    assert "private-provider-body" not in str(error.value)


def test_graph_can_discover_then_review_same_cluster_without_refreshing_map(tmp_path, monkeypatch):
    from ship_agent.runtime.agent import build_agent
    import ship_agent.clients.carrier_reference_client as carrier_reference_client
    import ship_agent.vision.image_review as image_review
    module, library = setup_review(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "request_carrier_hotspots", lambda _: {
        "status": "complete", "report_id": REVIEW["report_id"], "clusters": [{"cluster_id": REVIEW["cluster_id"]}]})
    monkeypatch.setattr(module, "request_carrier_hotspot_candidates", lambda _: candidates([100, 300]))
    monkeypatch.setattr(carrier_reference_client, "load_carrier_references", lambda: library)
    downloaded = []
    def pixels(row, *_):
        downloaded.append(row["observation_id"])
        return png("green")
    monkeypatch.setattr(image_review, "_image_bytes", pixels)
    class Planner:
        calls = 0
        def bind_tools(self, tools):
            assert {"find_carrier_hotspots", "investigate_carrier_hotspot"} <= {item.name for item in tools}
            return self
        def invoke(self, messages, **kw):
            self.calls += 1
            assert "eps=30 km, min_samples=2" in messages[0].content
            if self.calls < 3:
                name = "find_carrier_hotspots" if self.calls == 1 else "investigate_carrier_hotspot"
                args = QUERY if self.calls == 1 else REVIEW
                return AIMessage(content="", tool_calls=[{"id": str(self.calls), "name": name, "args": args}])
            result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert [item["priority"] for item in result["flags"]] == [1, 2]
            assert sum(block["type"] == "image_url" for block in messages[-1].content) == 1 + len(library.images)
            return AIMessage(content="Cụm 1 có hai trường hợp cần kiểm tra thủ công.")
    model = Planner()
    state = build_agent(model=model, observations=candidates([100, 300])["ships"]).invoke({"messages": [HumanMessage(
        content="Tìm khu vực nhiều lượt nghi tàu sân bay năm 2025 rồi kiểm tra chi tiết.")]})
    assert model.calls == 3 and downloaded == ["1"] and "<iframe" not in state["messages"][-1].text
