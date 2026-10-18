"""Frozen-demo queries, actual image bytes, and graph output without live services."""

import base64
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import re

from fastapi.testclient import TestClient
import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from PIL import Image
import pytest

from ship_agent.agent import build_agent
from ship_agent.demo import create_app
from ship_agent.demo_data import demo_image_markdown, image_path, read_snapshot
from ship_agent.report_artifacts import render_carrier_artifact
from ship_agent.tools import create_tools


@pytest.fixture
def demo_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("VESSELWATCH_DEMO_DIR", str(tmp_path))
    monkeypatch.setenv("VESSELWATCH_DEMO_PUBLIC_URL", "http://viewer:8002")
    images = tmp_path / "images"
    images.mkdir()
    output = BytesIO()
    Image.new("RGB", (4, 8), "navy").save(output, format="PNG")
    raw = output.getvalue()
    rows = []
    for index, (day, positive, length) in enumerate([
        ("2025-12-30", True, 350), ("2025-12-25", False, 150),
        ("2025-06-25", True, 315),
    ], 1):
        ship_id = f"DEMO_{index:03d}"
        filename = ship_id + ".png"
        (images / filename).write_bytes(raw)
        rows.append({
            "observation_id": f"source-observation-{index}", "ship_id": ship_id,
            "observed_date": day, "observed_at": day + "T02:00:00Z",
            "length_m": length, "width_m": 80 if positive else 25,
            "position": {"latitude": 19.0, "longitude": 112.0},
            "classification": "aircraft_carrier" if positive else "not_aircraft_carrier",
            "confidence": 0.98 if positive else 0.1, "image_id": ship_id,
            "image_file": filename, "image_sha256": hashlib.sha256(raw).hexdigest(),
        })
    snapshot = {"schema_version": 1, "reference_date": "2025-12-30", "observations": rows}
    snapshot["snapshot_id"] = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8"),
    ).hexdigest()
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return snapshot, raw, path


def test_demo_entry_point_loads_as_a_file_without_package_context():
    path = Path(__file__).resolve().parents[2] / "ship_agent/demo.py"
    spec = importlib.util.spec_from_file_location("demo_graph_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.make_graph) and callable(module.create_app)


def test_demo_search_counts_and_report_share_the_same_source(demo_snapshot, monkeypatch):
    from ship_agent import tools as tools_module
    monkeypatch.setattr(tools_module, "load_observations", lambda: pytest.fail("No production API in demo"))
    monkeypatch.setattr(tools_module, "load_daily_carrier_report", lambda *a: pytest.fail("No report HTTP in demo"))
    count, search, report = create_tools(data_source="demo")
    found = search.invoke({"classification": "aircraft_carrier", "min_length_m": 330})
    assert found["reference_date"] == "2025-12-30"
    assert found["is_demo"] and not found["is_mock"]
    assert [row["ship_id"] for row in found["ships"]] == ["DEMO_001"]
    assert found["ships"][0]["images"][0]["url"] == "http://viewer:8002/images/DEMO_001"
    assert found["ships"][0]["observed_date"] == "2025-12-30"
    args = {"observed_from": "2025-12-24", "observed_to": "2025-12-30"}
    stats, result = count.invoke(args), report.invoke(args)
    assert len(stats["daily_stats"]) == 7
    assert sum(row["suspicious_ship_count"] for row in stats["daily_stats"]) == 2
    assert result["total_detections"] == 1
    assert result["total_detections"] == sum(row["possible_aircraft_carrier_count"] for row in stats["daily_stats"])
    assert result["chart_url"] is None


def test_demo_artifact_embeds_only_matching_original_crops(demo_snapshot):
    _, raw, _ = demo_snapshot
    report = create_tools(data_source="demo")[2].invoke({
        "observed_from": "2025-12-24", "observed_to": "2025-12-30",
    })
    html = render_carrier_artifact(report)
    images = re.findall(r'<img src="data:image/png;base64,([^"]+)"', html)
    assert len(images) == 1 and base64.b64decode(images[0]) == raw
    assert "DEMO_001" in html and "DEMO_002" not in html and "DEMO_003" not in html
    assert "BỘ DỮ LIỆU DEMO" in html and "không chạy nhận diện mới" in html
    assert "http://viewer" not in html
    report["demo_snapshot_id"] = "another snapshot"
    with pytest.raises(ValueError, match="same snapshot"):
        render_carrier_artifact(report)


def test_demo_image_api_enlarges_preview_but_preserves_original(demo_snapshot):
    _, raw, _ = demo_snapshot
    with TestClient(create_app()) as client:
        assert client.get("/health").json()["is_demo"]
        preview = client.get("/images/DEMO_001")
        assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
        with Image.open(BytesIO(preview.content)) as image:
            assert image.size == (240, 480)
        assert client.get("/images/DEMO_001?original=true").content == raw
        assert client.get("/ships/DEMO_001").json()["observed_at"] == "2025-12-30T02:00:00Z"
        assert client.get("/images/missing").status_code == 404
        preview = client.get("/report-preview")
        assert preview.status_code == 200 and preview.text.count("<img ") == 1


def test_demo_rejects_modified_manifest_and_images(demo_snapshot):
    snapshot, _, path = demo_snapshot
    image_path(snapshot["observations"][0]).write_bytes(b"different crop")
    with pytest.raises(ValueError, match="saved model input"):
        image_path(snapshot["observations"][0])
    snapshot["observations"][0]["length_m"] = 999
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(ValueError, match="modified"):
        read_snapshot()


def test_demo_refuses_paths_outside_registered_image_root(demo_snapshot):
    snapshot, _, _ = demo_snapshot
    row = {**snapshot["observations"][0], "image_file": "../other.png"}
    with pytest.raises(ValueError, match="Invalid demo image path"):
        image_path(row)


def test_demo_does_not_reuse_images_from_previous_turn_or_duplicate_markdown(demo_snapshot):
    result = create_tools(data_source="demo")[1].invoke({"ship_id": "DEMO_001"})
    tool = ToolMessage(content=json.dumps(result), name="search_ships", tool_call_id="search")
    question = HumanMessage(content="Cho tôi xem ảnh DEMO_001")
    markdown = demo_image_markdown([question, tool], "Thông tin tàu.")
    assert markdown == "![DEMO_001](http://viewer:8002/images/DEMO_001)"
    assert demo_image_markdown([question, tool], markdown) == ""
    assert demo_image_markdown([question, tool, HumanMessage(content="Cho tôi xem ảnh khác")], "") == ""
    assert demo_image_markdown([HumanMessage(content="Chưa cần hiển thị ảnh"), tool], "") == ""
    error = ToolMessage(content="Not found", name="search_ships", tool_call_id="bad", status="error")
    assert demo_image_markdown([question, tool, error], "") == ""


@pytest.mark.parametrize("stream", [False, True])
def test_demo_graph_attaches_current_image_when_model_omits_it(demo_snapshot, stream):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert "Bộ dữ liệu demo cố định" in body["messages"][0]["content"]
        assert "ngày tham chiếu là 2025-12-30" in body["messages"][0]["content"].lower()
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "search", "type": "function", "function": {
                    "name": "search_ships", "arguments": '{"ship_id":"DEMO_001"}',
                },
            }]}
            reason = "tool_calls"
        else:
            result = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "tool"))
            assert result["ships"][0]["ship_id"] == "DEMO_001"
            message = {"role": "assistant", "content": "Quan sát DEMO_001 trong bộ demo."}
            reason = "stop"
        if body.get("stream"):
            delta = dict(message)
            if delta.get("tool_calls"):
                delta["tool_calls"] = [{"index": i, **call} for i, call in enumerate(delta["tool_calls"])]
            chunks = [
                {"id": "demo", "object": "chat.completion.chunk", "created": 0, "model": "test",
                 "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"id": "demo", "object": "chat.completion.chunk", "created": 0, "model": "test",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]},
            ]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
                "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            ).encode())
        return httpx.Response(200, json={
            "id": "chatcmpl-demo", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "message": message, "finish_reason": reason}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="test", api_key="synthetic", http_client=client, max_retries=0)
        graph = build_agent(model=model, data_source="demo")
        inputs = {"messages": [HumanMessage(content="Cho tôi xem ảnh tàu DEMO_001")]}
        if stream:
            events = list(graph.stream(inputs, stream_mode="messages"))
            answers = [m for m, _ in events if isinstance(m, AIMessage) and not m.tool_calls and m.content]
            assert len(answers) == 1
            answer = answers[0].content
        else:
            answer = graph.invoke(inputs)["messages"][-1].content
    assert len(requests) == 2
    assert answer.endswith("![DEMO_001](http://viewer:8002/images/DEMO_001)")
