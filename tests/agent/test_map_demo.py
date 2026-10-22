"""Frozen Leaflet snapshots and iframe artifacts without live HTTP or LLM calls."""

import base64
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException
from langchain_openai import ChatOpenAI
import pytest

from ship_agent.runtime.agent import build_agent
from ship_agent.runtime.demo import create_app
from ship_agent.artifacts.map_artifacts import render_map_artifact
from ship_agent.artifacts.map_snapshots import MapFilters
from ship_agent.artifacts.map_snapshots import map_root
from ship_agent.artifacts.map_snapshots import request_map
from ship_agent.tools.registry import create_tools
from tests.agent.test_demo import demo_snapshot

import ship_agent.tools.maps as maps_tools


QUERY = {"observed_from": "2025-12-24", "observed_to": "2025-12-30",
         "classification": "aircraft_carrier"}


def create_map(client, snapshot, query=None):
    response = client.post("/maps", json={**(query or QUERY), "expected_snapshot_id": snapshot["snapshot_id"]})
    assert response.status_code == 200, response.text
    return response.json()


def embedded_data(html):
    return json.loads(re.search(r'<script id="embedded-data" type="application/json">(.*?)</script>', html, re.S)[1])


def test_map_filters_match_search_and_return_only_small_summary(demo_snapshot):
    snapshot, raw, _ = demo_snapshot
    with TestClient(create_app()) as client:
        result = create_map(client, snapshot)
        assert result["total"] == create_tools(data_source="demo")[1].invoke(QUERY)["total"] == 1
        assert len(json.dumps(result)) < 1500 and "vessels" not in result
        response = client.get(urlsplit(result["map_url"]).path)
        assert response.status_code == 200 and "text/html" in response.headers["content-type"]
        data = embedded_data(response.text)
        assert [vessel["name"] for vessel in data["vessels"]] == ["source-ship-1"]
        assert base64.b64decode(data["vessels"][0]["image_path"].split(",")[1]) == raw
        assert data["vessels"][0]["metadata"]["width_m"] == 80
        assert "L.map(" in response.text and "__LEAFLET_" not in response.text
        assert "search();" in response.text and not data.get("api")
        assert create_map(client, snapshot) == result
        assert create_map(client, snapshot, {**QUERY, "ship_id": "source-ship-2"})["total"] == 0
        assert create_map(client, snapshot, {**QUERY, "min_length_m": 351})["total"] == 0


def test_saved_map_survives_restart_and_source_image_changes(demo_snapshot):
    snapshot, raw, snapshot_path = demo_snapshot
    with TestClient(create_app()) as client:
        result = create_map(client, snapshot)
        original = client.get(urlsplit(result["map_url"]).path).text
    updated_raw = raw + b"updated crop"
    (snapshot_path.parent / "images" / snapshot["observations"][0]["image_file"]).write_bytes(updated_raw)
    snapshot["observations"][0]["image_sha256"] = hashlib.sha256(updated_raw).hexdigest()
    snapshot.pop("snapshot_id")
    snapshot["snapshot_id"] = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8"),
    ).hexdigest()
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    with TestClient(create_app()) as restarted:
        assert restarted.get(urlsplit(result["map_url"]).path).text == original
        assert create_map(restarted, snapshot)["map_id"] != result["map_id"]


@pytest.mark.parametrize("query", [
    {**QUERY, "observed_to": "2025-12-23"},
    {**QUERY, "observed_from": "2024-01-01"},
    {**QUERY, "observed_from": "2025-02-30"},
    {**QUERY, "min_width_m": 90, "max_width_m": 80},
    {**QUERY, "min_length_m": -1},
    {**QUERY, "classification": "unsupported"},
    {**QUERY, "limit": 1},
])
def test_map_rejects_invalid_filters(demo_snapshot, query):
    snapshot, _, _ = demo_snapshot
    with TestClient(create_app()) as client:
        assert client.post("/maps", json={**query, "expected_snapshot_id": snapshot["snapshot_id"]}).status_code == 422
    assert not map_root().exists()


def test_map_rejects_stale_source_and_tampered_saved_data(demo_snapshot):
    snapshot, _, _ = demo_snapshot
    with TestClient(create_app()) as client:
        assert client.post("/maps", json={**QUERY, "expected_snapshot_id": "0" * 64}).status_code == 409
        assert client.get("/maps/not-an-id").status_code == 404
        assert client.get("/maps/" + "0" * 64).status_code == 404
        result = create_map(client, snapshot)
        path = map_root() / f"{result['map_id']}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["vessels"] = []
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert client.get(urlsplit(result["map_url"]).path).status_code == 409


def test_map_client_separates_internal_and_public_urls(demo_snapshot, monkeypatch):
    snapshot, _, _ = demo_snapshot
    monkeypatch.setenv("VESSELWATCH_DEMO_API_URL", "http://demo-internal:8002")
    filters = MapFilters(**QUERY)

    def respond(request):
        assert str(request.url) == "http://demo-internal:8002/maps"
        assert json.loads(request.content)["expected_snapshot_id"] == snapshot["snapshot_id"]
        return httpx.Response(200, json={
            "source_snapshot_id": snapshot["snapshot_id"], "filters": filters.model_dump(),
            "map_id": "a" * 64, "total": 1, "map_url": "http://untrusted.example/map",
            "html": "Large viewer must not enter model context",
        })

    result = request_map(filters, snapshot["snapshot_id"], transport=httpx.MockTransport(respond))
    assert result["map_url"] == "http://viewer:8002/maps/" + "a" * 64
    assert "html" not in result


def test_map_tool_failure_does_not_return_an_old_map(demo_snapshot, monkeypatch):

    def fail(*args):
        raise httpx.ConnectError("Demo server offline")

    monkeypatch.setattr(maps_tools, "request_map", fail)
    with pytest.raises(ToolException, match="8002"):
        create_tools(data_source="demo")[3].invoke(QUERY)


@pytest.mark.parametrize("stream", [False, True])
def test_graph_attaches_small_iframe_and_keeps_leaflet_out_of_llm_context(demo_snapshot, monkeypatch, stream):

    snapshot, _, _ = demo_snapshot
    with TestClient(create_app()) as backend:
        def call_backend(filters, snapshot_id):
            assert snapshot_id == snapshot["snapshot_id"]
            return create_map(backend, snapshot, filters.model_dump())

        monkeypatch.setattr(maps_tools, "request_map", call_backend)
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            assert "leaflet.js" not in request.content.decode()
            assert "L.map(" not in request.content.decode()
            if len(requests) == 1:
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "map", "type": "function", "function": {
                        "name": "create_vessel_map", "arguments": json.dumps(QUERY),
                    },
                }]}
                reason = "tool_calls"
            else:
                if len(requests) == 2:
                    result = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "tool"))
                    assert result["total"] == 1 and len(json.dumps(result)) < 1500
                message = {"role": "assistant", "content": "Một lượt quan sát."}
                reason = "stop"
            if body.get("stream"):
                delta = dict(message)
                if delta.get("tool_calls"):
                    delta["tool_calls"] = [{"index": i, **call} for i, call in enumerate(delta["tool_calls"])]
                chunks = [
                    {"id": "map", "object": "chat.completion.chunk", "created": 0, "model": "test",
                     "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    {"id": "map", "object": "chat.completion.chunk", "created": 0, "model": "test",
                     "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]},
                ]
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
                    "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
                ).encode())
            return httpx.Response(200, json={
                "id": "map", "object": "chat.completion", "created": 0, "model": "test",
                "choices": [{"index": 0, "message": message, "finish_reason": reason}],
            })

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            model = ChatOpenAI(model="test", api_key="synthetic", http_client=client, max_retries=0)
            graph = build_agent(model=model, data_source="demo")
            inputs = {"messages": [HumanMessage(content="Hiển thị tàu sân bay từ 24 đến 30/12/2025 trên bản đồ.")]}
            if stream:
                events = list(graph.stream(inputs, stream_mode="messages"))
                answers = [m for m, _ in events if isinstance(m, AIMessage) and not m.tool_calls and m.content]
                assert len(answers) == 1
                answer = answers[0]
            else:
                answer = graph.invoke(inputs)["messages"][-1]
            assert "```html\n<!DOCTYPE html>" in answer.text and "<iframe src=" in answer.text
            assert "Mở bản đồ toàn màn hình" in answer.text and len(answer.text) < 2000
            assert "base64" not in answer.text
            # Follow-up includes only the small wrapper, and must not reattach the map.
            result = graph.invoke({"messages": [*inputs["messages"], answer, HumanMessage(content="Cảm ơn.")]})
            assert "<iframe" not in result["messages"][-1].text
            chat_messages = [m for m in requests[-1]["messages"] if m["role"] != "system"]
            assert len(json.dumps(chat_messages)) < 2000


def test_artifact_escapes_url_attributes():
    html = render_map_artifact({"map_url": 'https://viewer.example/maps/a?x="<test>', "total": 0})
    assert '&quot;&lt;test&gt;' in html and 'x="<test>' not in html


def test_failed_map_correction_suppresses_earlier_success(demo_snapshot):
    snapshot, _, _ = demo_snapshot
    with TestClient(create_app()) as backend:
        result = create_map(backend, snapshot)

    def respond(request):
        return httpx.Response(200, json={
            "id": "map-error", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "Chưa tạo được bản đồ mới."}}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="test", api_key="synthetic", http_client=client, max_retries=0)
        graph = build_agent(model=model, data_source="demo")
        response = graph.invoke({"messages": [
            HumanMessage(content="Mở bản đồ."),
            ToolMessage(content=json.dumps(result), name="create_vessel_map", tool_call_id="old"),
            ToolMessage(content="Server offline", name="create_vessel_map", tool_call_id="new", status="error"),
        ]})
        assert "<iframe" not in response["messages"][-1].text


@pytest.mark.parametrize("ship_id", [None, "missing"])
def test_map_application_autoloads_markers_and_selected_image_without_fetch(demo_snapshot, ship_id):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise the map application script")
    snapshot, _, _ = demo_snapshot
    with TestClient(create_app()) as client:
        result = create_map(client, snapshot, {**QUERY, "ship_id": ship_id})
        html = client.get(urlsplit(result["map_url"]).path).text

    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.elements = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                self.elements[attrs["id"]] = {"tag": tag, "hidden": "hidden" in attrs,
                                              "checked": "checked" in attrs}

    parser = Elements()
    parser.feed(html)
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.S)
    completed = subprocess.run(
        [node, str(Path(__file__).with_name("map_dom_probe.cjs"))],
        input=json.dumps({"elements": parser.elements, "dataset": embedded_data(html), "script": scripts[-1]}),
        text=True, capture_output=True, check=True, timeout=10,
    )
    assert "Map application probe passed" in completed.stdout
