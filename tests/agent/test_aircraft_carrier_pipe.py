"""Existing Pipe + real local selection HTTP API; LangGraph is simulated."""

import asyncio
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.file_server.test_chat_areas import SQUARE, session_server
from ship_agent.chat_area import apply_chat_area


@pytest.fixture
def pipe_module(monkeypatch):
    # SDK is absent in the lightweight development environment; no installation needed.
    sdk = ModuleType("langgraph_sdk")
    client = ModuleType("langgraph_sdk.client")
    schema = ModuleType("langgraph_sdk.schema")
    client.get_client = lambda **kwargs: None
    class Command:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
    schema.Command = Command
    monkeypatch.setitem(sys.modules, "langgraph_sdk", sdk)
    monkeypatch.setitem(sys.modules, "langgraph_sdk.client", client)
    monkeypatch.setitem(sys.modules, "langgraph_sdk.schema", schema)
    path = Path(__file__).resolve().parents[2] / "scripts/aircraft_carrier_pipe.py"
    spec = importlib.util.spec_from_file_location("carrier_pipe_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(text, chat="chat-1"):
    return {"body": {"messages": [{"role": "user", "content": text}]},
            "__metadata__": {"user_id": "u", "chat_id": chat, "message_id": "m", "model": {}},
            "__user__": {"email": "u@example.test"}}


def collect(pipe, **kwargs):
    async def run():
        return [item async for item in pipe.pipe(**kwargs)]
    return asyncio.run(run())


def fake_graph(pipe):
    calls = []
    class Threads:
        async def create(self, **kwargs):
            return {"thread_id": kwargs["thread_id"]}
        async def get_state(self, thread_id):
            return {"interrupts": []}
    class Runs:
        async def stream(self, **kwargs):
            calls.append(kwargs)
            yield SimpleNamespace(event="messages", data=[{"content": "Trả lời"}, {"langgraph_node": "agent"}])
    pipe.client = SimpleNamespace(threads=Threads(), runs=Runs())
    return calls


def test_map_and_questions_use_same_chat_and_fresh_confirmed_json(pipe_module, session_server):
    base, store = session_server
    pipe = pipe_module.Pipe()
    pipe.valves.MAP_API_URL = base
    pipe.valves.MAP_URL = "http://viewer:18000/demo/vessel_map.html?keep=1"
    calls = fake_graph(pipe)
    artifact = "".join(item for item in collect(pipe, **request("map")) if isinstance(item, str))
    assert "```html" in artifact and len(calls) == 0
    class Frames(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "iframe":
                self.url = dict(attrs)["src"]
    parser = Frames()
    parser.feed(artifact)
    token = parse_qs(urlsplit(parser.url).query)["map_session"][0]
    assert parse_qs(urlsplit(parser.url).query)["keep"] == ["1"]
    assert store.get(token)["chat_id"] == "chat-1"
    store.set_area(token, SQUARE, 0)
    collect(pipe, **request("Trong vùng vừa vẽ có bao nhiêu tàu?"))
    assert calls[-1]["thread_id"] == "chat-1"
    first_config = calls[-1]["config"]
    assert apply_chat_area({}, first_config)["polygon"] == SQUARE
    assert "```html" not in str(calls[-1]["input"])
    store.set_area(token, None, 1)
    collect(pipe, **request("Hỏi lại vùng này"))
    assert calls[-1]["config"]["configurable"]["chat_area_context"]["active_area"] is None
    with pytest.raises(ValueError):
        apply_chat_area({}, calls[-1]["config"])
    assert apply_chat_area({}, first_config)["polygon"] == SQUARE  # In-flight snapshot stays immutable.
    collect(pipe, **request("Vùng của chat khác?", chat="chat-2"))
    assert calls[-1]["config"]["configurable"]["chat_area_context"]["active_area"] is None


def test_disabled_or_failed_map_does_not_reuse_old_polygon(pipe_module):
    pipe = pipe_module.Pipe()
    calls = fake_graph(pipe)
    collect(pipe, **request("Câu hỏi bình thường"))
    assert calls[-1]["config"]["configurable"]["chat_area_context"] is None
    pipe.valves.MAP_URL = "file:///invalid"
    collect(pipe, **request("Hỏi vùng đang chọn"))
    context = calls[-1]["config"]["configurable"]["chat_area_context"]
    assert context["error"] == "map_api_unavailable" and "active_area" not in context
    with pytest.raises(ValueError):
        apply_chat_area({}, calls[-1]["config"])
    before = len(calls)
    collect(pipe, **request("map"))
    collect(pipe, **request("title"), __task__="title_generation")
    assert len(calls) == before
