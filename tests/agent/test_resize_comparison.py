"""The A/B experiment varies only target pixels and keeps the exact model responses."""

import base64
from copy import deepcopy
from io import BytesIO
import json

from PIL import Image
import pytest

pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage
from file_server.media.carrier_references import load_reference_library
from ship_agent.vision.resize_comparison import compare_resize, write_comparison_report
from tests.file_server.test_carrier_references import png, reference_folder


def test_only_target_pixels_change_and_model_does_not_see_other_answer(tmp_path):
    library = load_reference_library(reference_folder(tmp_path))
    calls = []
    class Reviewer:
        model_name = "synthetic-test-model"
        def invoke(self, messages, **kwargs):
            calls.append(deepcopy(messages))
            return AIMessage(content="first raw answer" if len(calls) == 1 else "second raw answer")
    report, variants = compare_resize(png(size=(48, 26)), observation_id="real-id",
                                     model=Reviewer(), library=library)
    assert len(calls) == 2 and all(len(messages) == 2 for messages in calls)
    assert calls[0][0].content == calls[1][0].content
    first, second = calls[0][1].content, calls[1][1].content
    assert first[0] == second[0] and first[2:] == second[2:]
    assert first[1] != second[1]
    for content, size in ((first, (48, 26)), (second, (224, 121))):
        encoded = content[1]["image_url"]["url"].split(",", 1)[1]
        with Image.open(BytesIO(base64.b64decode(encoded))) as image:
            assert image.size == size
    assert [item["raw_response"] for item in report["conditions"]] == ["first raw answer", "second raw answer"]
    assert all(item["status"] == "invalid_response" for item in report["conditions"])
    assert report["reference_revision"] == library.revision
    path = write_comparison_report(report, variants, tmp_path / "report")
    assert "first raw answer" in path.read_text(encoding="utf-8")
    assert "data:image" not in (path.parent / "comparison.json").read_text(encoding="utf-8")


def test_prepare_only_does_not_call_model_and_report_escapes_model_text(tmp_path):
    class Forbidden:
        def invoke(self, *args, **kwargs):
            pytest.fail("Preparation must not call an API")
    report, variants = compare_resize(png(size=(48, 26)), observation_id="id", model=Forbidden(), prepare_only=True)
    assert all(item["status"] == "prepared" for item in report["conditions"])
    report["conditions"][0]["raw_response"] = "<script>alert('model')</script>"
    path = write_comparison_report(report, variants, tmp_path / "comparison")
    assert "<script>" not in path.read_text(encoding="utf-8")
    assert "&lt;script&gt;" in path.read_text(encoding="utf-8")
    assert json.loads((path.parent / "comparison.json").read_text(encoding="utf-8"))["prepare_only"]
    with pytest.raises(FileExistsError):
        write_comparison_report(report, variants, path.parent)


def test_no_duplicate_requests_when_input_already_meets_resize_policy():
    with pytest.raises(ValueError):
        compare_resize(png(size=(224, 224)), observation_id="id", prepare_only=True)


def test_failure_does_not_drop_the_other_condition_or_expose_provider_body():
    class Reviewer:
        calls = 0
        def invoke(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("sensitive request body")
            return AIMessage(content=json.dumps({"assessment": "unknown", "image_quality": "insufficient",
                "visible_features": ["tiny"], "limitations": ["too small"], "reasoning": "unclear"}))
    report, _ = compare_resize(png(size=(48, 26)), observation_id="id", model=Reviewer())
    assert report["conditions"][0]["status"] == "request_failed"
    assert report["conditions"][1]["raw_response"] is not None
    assert report["conditions"][1]["status"] == "complete"
    assert "sensitive request body" not in json.dumps(report)


def test_cli_prepare_only_wires_source_references_and_report(tmp_path, monkeypatch, capsys):
    from ship_agent.vision.cli import main
    import ship_agent.clients.file_server_client as source
    import ship_agent.clients.carrier_reference_client as references
    import ship_agent.vision.image_review as reviewer
    monkeypatch.setattr(source, "load_observations", lambda: [{"observation_id": "id", "images": [{"image_id": "image"}]}])
    monkeypatch.setattr(reviewer, "_image_bytes", lambda *args: png(size=(48, 26)))
    monkeypatch.setattr(references, "load_carrier_references", lambda: load_reference_library(reference_folder(tmp_path)))
    directory = tmp_path / "output"
    monkeypatch.setattr("sys.argv", ["image_review", "--data-source", "file_server", "--observation-id", "id",
        "--compare-resize", "--use-carrier-references", "--prepare-only", "--output-dir", str(directory)])
    main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["conditions"][0]["status"] == "prepared"
    assert (directory / "comparison.html").exists()
    report = json.loads((directory / "comparison.json").read_text(encoding="utf-8"))
    assert report["reference_count"] == 1 and report["model"] is None
