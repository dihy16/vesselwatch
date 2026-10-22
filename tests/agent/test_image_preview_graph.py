"""The final graph message has a preview while source/tool/pixel inputs stay separate."""

from copy import deepcopy
import json

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langchain_openai")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from file_server.media.carrier_references import load_reference_library
from ship_agent.runtime.agent import build_agent
from tests.file_server.test_carrier_references import reference_folder
from tests.integration.test_label_review_client import payload


def test_search_only_chat_response_is_resized_without_fetching_pixels():
    row = payload()["ships"][0]
    row["images"][0]["url"] = "http://public/images/" + row["images"][0]["image_id"]
    before = deepcopy(row)
    raw = row["images"][0]["url"]

    class Planner:
        calls = 0
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, config=None):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "id": "search", "name": "search_ships", "args": {"limit": 1}}])
            tool_result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert tool_result["ships"][0]["images"][0]["url"] == raw
            assert config == {"tags": ["nostream"]}
            return AIMessage(content=f"![Tàu]({raw})")

    state = build_agent(model=Planner(), observations=[row]).invoke({"messages": [HumanMessage(content="Cho xem ảnh.")]})
    assert f"![Tàu]({raw}?preview=1)" in state["messages"][-1].content
    assert f"]({raw})" in state["messages"][-1].content
    assert row == before


def test_reference_view_returns_real_display_urls_and_a_clickable_preview(tmp_path, monkeypatch):
    from ship_agent.clients import carrier_reference_client
    from ship_agent.tools import images

    library = load_reference_library(reference_folder(tmp_path))
    for module in (carrier_reference_client, images):
        monkeypatch.setattr(module, "load_carrier_references", lambda: library)

    class Planner:
        calls = 0
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, config=None):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"id": "refs", "name": "view_carrier_references", "args": {}}])
            result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            image = result["reference_images"][0]
            assert image["reference_id"] in image["url"] and "preview=1" in image["preview_url"]
            assert config == {"tags": ["nostream"]}
            return AIMessage(content=f'![ref1]({image["url"]})')

    state = build_agent(model=Planner(), observations=[]).invoke({"messages": [HumanMessage(content="Mở ảnh mẫu.")]})
    final = state["messages"][-1].content
    assert "preview=1" in final and "gốc 32×24 px" in final
    assert "data:image" not in json.dumps([message.model_dump() for message in state["messages"]])
