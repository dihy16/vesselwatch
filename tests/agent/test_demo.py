"""Frozen-demo queries, actual image bytes, and graph output without live services."""

import base64
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from PIL import Image
import pytest

from ship_agent.runtime.agent import build_agent
from ship_agent.runtime.demo import create_app
from ship_agent.data.demo_data import demo_image_markdown
from ship_agent.data.demo_data import image_path
from ship_agent.data.demo_data import read_snapshot
from ship_agent.artifacts.report_artifacts import render_carrier_artifact
from ship_agent.tools.registry import create_tools


@pytest.mark.parametrize("invalid_id", [None, "missing", "duplicate", "same_capture"])
def test_prepare_demo_preserves_source_ship_ids(tmp_path, monkeypatch, invalid_id):
    from scripts import prepare_demo_data

    source = tmp_path / "source"
    demo = source / "demo"
    demo.mkdir(parents=True)
    run = demo / "run/offline_cloud_crop_staged"
    run.mkdir(parents=True)
    (demo / "local_config.json").write_text(json.dumps({
        "manifest": "manifest.json", "saved_run_dir": "run",
    }), encoding="utf-8")
    (demo / "saved_run_results.py").write_text(
        "def apply_saved_results(rows, run, seed):\n    pass\n", encoding="utf-8",
    )
    (run / "report.json").write_text(json.dumps({
        "threshold": 0.5, "model": "test-model",
    }), encoding="utf-8")
    ship_ids = ["fb21fe76-1b74-4ee3-af60-be68f2e1b20b",
                "S2C_MSIL2A_20250625T030601_N0511_R075_T49QCU_20250625T064400_0"]
    rows, digests = [], []
    for index, ship_id in enumerate([*ship_ids, "alternate-crop-same-acquisition"]):
        raw = BytesIO()
        Image.new("RGB", (4, 8), (index, 0, 0)).save(raw, format="PNG")
        filename = f"crop-{index}.png"
        (demo / filename).write_bytes(raw.getvalue())
        digest = hashlib.sha256(raw.getvalue()).hexdigest()
        digests.append(digest)
        rows.append({
            "id": f"observation-{index}", "name": filename, "image_path": filename,
            "captured_at": "2025-12-30T02:00:00Z", "latitude": 19 + index % 2, "longitude": 112,
            "prediction": {"carrier_score": 0.98},
            "metadata": {"source_id": ship_id, "crop_sha256": digest,
                         "ground_truth_label": "Carrier present", "length_m": 350, "width_m": 80},
        })
    if invalid_id == "missing":
        del rows[0]["metadata"]["source_id"]
    elif invalid_id == "duplicate":
        rows[1]["metadata"]["source_id"] = ship_ids[0]
    elif invalid_id == "same_capture":
        rows[1]["latitude"] = rows[0]["latitude"] + 0.00002
    (demo / "manifest.json").write_text(json.dumps({
        "image_root": ".", "vessels": rows,
    }), encoding="utf-8")
    monkeypatch.setattr(prepare_demo_data, "CARRIER_DIGESTS", tuple(digests[:2]))
    output = tmp_path / "snapshot"
    if invalid_id:
        with pytest.raises(ValueError, match="Missing source ship ID|Duplicate source ship ID|same acquisition"):
            prepare_demo_data.write_snapshot(source, output)
        assert not output.exists()
        return

    snapshot = prepare_demo_data.write_snapshot(source, output)
    monkeypatch.setenv("VESSELWATCH_DEMO_DIR", str(output))
    assert read_snapshot() == snapshot
    assert [row["ship_id"] for row in snapshot["observations"]] == ship_ids
    for index, row in enumerate(snapshot["observations"]):
        assert row["ship_id"] == row["source_id"]
        assert image_path(row).read_bytes() == (demo / f"crop-{index}.png").read_bytes()


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
        ship_id = f"source-ship-{index}"
        image_id = f"DEMO_{index:03d}"
        filename = image_id + ".png"
        (images / filename).write_bytes(raw)
        rows.append({
            "observation_id": f"source-observation-{index}", "ship_id": ship_id, "source_id": ship_id,
            "observed_date": day, "observed_at": day + "T02:00:00Z",
            "length_m": length, "width_m": 80 if positive else 25,
            "position": {"latitude": 19.0, "longitude": 112.0},
            "classification": "aircraft_carrier" if positive else "not_aircraft_carrier",
            "confidence": 0.98 if positive else 0.1, "image_id": image_id,
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


def test_packaged_demo_matches_recording_plan_without_duplicate_carrier_crops(monkeypatch):
    from ship_agent.artifacts.map_snapshots import MapFilters
    from ship_agent.artifacts.map_snapshots import select_records

    root = Path(__file__).resolve().parents[2] / "data/demo"
    monkeypatch.setenv("VESSELWATCH_DEMO_DIR", str(root))
    snapshot = read_snapshot()
    count, search, report, *_ = create_tools(data_source="demo")
    carriers = search.invoke({"classification": "aircraft_carrier"})["ships"]
    assert len(snapshot["observations"]) == 11 and len(carriers) == 3
    ids = {row["ship_id"] for row in carriers}
    assert "703342cf-2fca-4da5-a12a-e74f5bde065c" not in ids
    assert "3087952c-ba2b-4e74-b405-311025f5959d" in ids
    assert len({(row["position"]["latitude"], row["position"]["longitude"]) for row in carriers}) == 3
    filtered = search.invoke({"classification": "aircraft_carrier", "min_length_m": 330, "min_width_m": 75})
    assert {row["ship_id"] for row in filtered["ships"]} == {
        "fb21fe76-1b74-4ee3-af60-be68f2e1b20b", "3087952c-ba2b-4e74-b405-311025f5959d",
    }
    week = {"observed_from": "2025-12-24", "observed_to": "2025-12-30"}
    stats = count.invoke(week)["daily_stats"]
    assert sum(row["suspicious_ship_count"] for row in stats) == 9
    assert report.invoke(week)["total_detections"] == 1
    assert stats[-1]["suspicious_ship_count"] == 3 and stats[-1]["possible_aircraft_carrier_count"] == 1
    on_map = select_records(snapshot, MapFilters(
        observed_from="2025-06-01", observed_to="2025-12-30", classification="aircraft_carrier",
    ))
    assert {row["ship_id"] for row in on_map} == ids


def test_demo_search_counts_and_report_share_the_same_source(demo_snapshot, monkeypatch):
    import ship_agent.tools.registry as tools_module
    import ship_agent.tools.reports as report_tools
    monkeypatch.setattr(tools_module, "load_observations", lambda: pytest.fail("No production API in demo"))
    monkeypatch.setattr(report_tools, "load_daily_carrier_report", lambda *a: pytest.fail("No report HTTP in demo"))
    count, search, report, *_ = create_tools(data_source="demo")
    found = search.invoke({"classification": "aircraft_carrier", "min_length_m": 330})
    assert found["reference_date"] == "2025-12-30"
    assert found["is_demo"] and not found["is_mock"]
    assert [row["ship_id"] for row in found["ships"]] == ["source-ship-1"]
    assert found["ships"][0]["images"][0]["url"] == "http://viewer:8002/images/DEMO_001"
    assert found["ships"][0]["observed_date"] == "2025-12-30"
    assert "demo" not in found["ships"][0]["images"][0]["caption"].lower()
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
    assert "source-ship-1" in html and "source-ship-2" not in html and "source-ship-3" not in html
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
        assert client.get("/ships/source-ship-1").json()["observed_at"] == "2025-12-30T02:00:00Z"
        assert client.get("/images/missing").status_code == 404
        preview = client.get("/report-preview")
        assert preview.status_code == 200 and preview.text.count("<img ") == 1


@pytest.mark.parametrize("last,expected_total", [("2025-12-30", 1), ("2025-12-29", 0)])
def test_demo_chart_png_matches_tool_and_rejects_stale_urls(demo_snapshot, monkeypatch, last, expected_total):
    import ship_agent.runtime.demo as demo_module

    captured = []
    render = demo_module.render_carrier_chart

    def render_and_capture(report):
        captured.append(report)
        return render(report)

    monkeypatch.setattr(demo_module, "render_carrier_chart", render_and_capture)
    report = create_tools(data_source="demo")[2].invoke({
        "observed_from": "2025-12-24", "observed_to": last, "output_format": "png",
    })
    assert report["output_format"] == "png" and report["total_detections"] == expected_total
    url = urlsplit(report["chart_url"])
    assert url.netloc == "viewer:8002" and url.path == "/charts/daily-carriers.png"
    params = {key: values[0] for key, values in parse_qs(url.query).items()}
    with TestClient(create_app()) as client:
        response = client.get(url.path, params=params)
        assert response.status_code == 200 and response.headers["content-type"] == "image/png"
        with Image.open(BytesIO(response.content)) as image:
            assert image.format == "PNG" and image.width > 1000 and image.height > 400
        assert captured[0]["daily_stats"] == report["daily_stats"]
        assert captured[0]["report_id"] == report["report_id"]
        for field in ("report_id", "snapshot_id"):
            assert client.get(url.path, params={**params, field: "0" * 64}).status_code == 409
        for first, end in [("2025-12-31", last), ("2024-01-01", last), ("invalid", last)]:
            assert client.get(url.path, params={
                **params, "observed_from": first, "observed_to": end,
            }).status_code == 422
        assert client.get(url.path, params={**params, "report_id": "invalid"}).status_code == 422
    assert len(captured) == 1


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
    result = create_tools(data_source="demo")[1].invoke({"ship_id": "source-ship-1"})
    tool = ToolMessage(content=json.dumps(result), name="search_ships", tool_call_id="search")
    question = HumanMessage(content="Cho tôi xem ảnh source-ship-1")
    markdown = demo_image_markdown([question, tool], "Thông tin tàu.")
    assert markdown == "![source-ship-1](http://viewer:8002/images/DEMO_001)"
    assert demo_image_markdown([question, tool], markdown) == ""
    assert demo_image_markdown([question, tool, HumanMessage(content="Cho tôi xem ảnh khác")], "") == ""
    assert demo_image_markdown([HumanMessage(content="Chưa cần hiển thị ảnh"), tool], "") == ""
    error = ToolMessage(content="Not found", name="search_ships", tool_call_id="bad", status="error")
    assert demo_image_markdown([question, tool, error], "") == ""


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("media", ["ship", "chart"])
def test_demo_graph_attaches_current_image_when_model_omits_it(demo_snapshot, stream, media):
    requests = []
    tool_name = "search_ships" if media == "ship" else "daily_carrier_report"
    arguments = ({"ship_id": "source-ship-1"} if media == "ship" else {
        "observed_from": "2025-12-24", "observed_to": "2025-12-30", "output_format": "png",
    })
    expected_image = "[![source-ship-1](http://viewer:8002/images/DEMO_001?preview=1)](http://viewer:8002/images/DEMO_001?original=1)"
    if media == "chart":
        report = create_tools(data_source="demo")[2].invoke(arguments)
        expected_image = f"![Biểu đồ lượt dự đoán tàu sân bay theo ngày]({report['chart_url']})"

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        prompt = body["messages"][0]["content"]
        assert "Trả lời trực tiếp kết quả người dùng hỏi" in prompt
        assert "Không tự thêm mục 'Lưu ý', 'Ghi chú'" in prompt
        assert "không nhắc đến demo, tập demo, bộ dữ liệu demo" in prompt
        assert "Chỉ giải thích các nội dung này khi người dùng hỏi trực tiếp" in prompt
        assert "Không khẳng định đang nhận diện ảnh mới" in prompt
        assert "Bộ dữ liệu demo cố định từ ShipClassification" not in prompt
        assert "ngày tham chiếu là 2025-12-30" in prompt.lower()
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "search", "type": "function", "function": {
                    "name": tool_name, "arguments": json.dumps(arguments),
                },
            }]}
            reason = "tool_calls"
        else:
            result = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "tool"))
            if media == "ship":
                assert result["ships"][0]["ship_id"] == "source-ship-1"
            else:
                assert result["output_format"] == "png" and result["total_detections"] == 1
            message = {"role": "assistant", "content": "Kết quả truy vấn."}
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
        question = ("Cho tôi xem ảnh tàu source-ship-1" if media == "ship"
                    else "Xuất ảnh chart PNG riêng từ 24/12/2025 đến 30/12/2025.")
        inputs = {"messages": [HumanMessage(content=question)]}
        if stream:
            events = list(graph.stream(inputs, stream_mode="messages"))
            answers = [m for m, _ in events if isinstance(m, AIMessage) and not m.tool_calls and m.content]
            assert len(answers) == 1
            answer = answers[0].content
        else:
            answer = graph.invoke(inputs)["messages"][-1].content
    assert len(requests) == 2
    assert answer.endswith(expected_image) and "```html" not in answer
