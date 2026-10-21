"""Direct chat input carries pixels, not just URLs or previous review text."""

import base64
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from file_server.carrier_references import load_reference_library
from ship_agent.visual_context import attach_visual_input, build_visual_content, latest_visual_input
from tests.agent.test_pair_evidence import pair_rows
from tests.file_server.test_carrier_references import png, reference_folder


@pytest.fixture
def library(tmp_path):
    reference_folder(tmp_path)
    (tmp_path / "second.png").write_bytes(png("red"))
    return load_reference_library(tmp_path)


def pixels(content):
    return [base64.b64decode(item["image_url"]["url"].split(",", 1)[1])
            for item in content if item["type"] == "image_url"]


@pytest.mark.parametrize("mode", ["references", "single", "pair", "generic"])
def test_chat_receives_all_pixels_for_each_supported_mode(library, mode):
    rows = list(pair_rows()) if mode == "pair" else [] if mode == "references" else [pair_rows()[0]]
    refs = None if mode == "generic" else library
    result = attach_visual_input({"status": "complete"}, rows, refs)
    assert "base64" not in json.dumps(result)
    before = deepcopy(result)
    content = build_visual_content(result["visual_input"], rows,
        load_references=lambda: library, load_image=lambda row: png("green"))
    assert pixels(content) == [png("green")] * len(rows) + ([image.data for image in library.images] if refs else [])
    assert result == before
    if refs:
        assert all(image.reference_id in json.dumps(content) for image in refs.images)
        assert library.description in json.dumps(content, ensure_ascii=False)


@pytest.mark.parametrize("failure", ["unknown-id", "wrong-image", "duplicate", "revision", "bad-revision", "extra-field"])
def test_no_arbitrary_url_or_mismatched_snapshot_reaches_image_loader(library, failure):
    rows = list(pair_rows())
    descriptor = attach_visual_input({}, rows, library)["visual_input"]
    if failure == "unknown-id":
        descriptor["targets"][0]["observation_id"] = "http://untrusted/image"
    elif failure == "wrong-image":
        descriptor["targets"][0]["image_id"] = "other-image"
    elif failure == "duplicate":
        descriptor["targets"].append(descriptor["targets"][0])
    elif failure == "revision":
        descriptor["reference_revision"] = "0" * 64
    elif failure == "bad-revision":
        descriptor["reference_revision"] = "http://untrusted/refs"
    else:
        descriptor["url"] = "http://untrusted/refs"
    with pytest.raises(ValueError):
        build_visual_content(descriptor, rows, load_references=lambda: library,
            load_image=lambda row: pytest.fail("Must validate identities and revision before pixels"))


def message(kind, descriptor=None, **kwargs):
    return SimpleNamespace(type=kind, name=kwargs.get("name", "review_ship_images"),
        status=kwargs.get("status", "success"), content=json.dumps(
            {"visual_input": descriptor} if descriptor is not None else {}))


def test_followup_requires_a_fresh_tool_and_errors_do_not_reuse_old_images(library):
    descriptor = attach_visual_input({}, list(pair_rows()), library)["visual_input"]
    history = [message("human"), message("ai"), message("tool", descriptor), message("ai")]
    assert latest_visual_input(history) == descriptor
    assert latest_visual_input([*history, message("human")]) is None
    assert latest_visual_input([*history, message("ai"), message("tool", status="error")]) is None
    assert latest_visual_input([*history, message("ai"), message("tool")]) is None


def test_parallel_calls_share_one_full_reference_set_and_deduplicate_targets(library):
    rows = list(pair_rows())
    single = attach_visual_input({}, rows[:1], library)["visual_input"]
    pair = attach_visual_input({}, rows, library)["visual_input"]
    refs = attach_visual_input({}, library=library)["visual_input"]
    history = [message("human"), message("ai"), message("tool", single), message("tool", pair),
               message("tool", refs, name="view_carrier_references")]
    assert latest_visual_input(history) == pair
    other = {**refs, "reference_revision": "0" * 64}
    with pytest.raises(ValueError):
        latest_visual_input([*history, message("tool", other)])


def test_loading_failure_is_not_a_partial_pixel_message(library):
    rows = list(pair_rows())
    descriptor = attach_visual_input({}, rows, library)["visual_input"]
    def fail_second(row):
        if row is rows[1]:
            raise OSError("Second image missing")
        return png("green")
    with pytest.raises(OSError):
        build_visual_content(descriptor, rows, load_references=lambda: library, load_image=fail_second)


@pytest.mark.parametrize("tool_name", ["investigate_carrier_detections", "investigate_carrier_hotspot", "vessel_monitoring_report", "investigate_carrier_labels"])
def test_dimension_only_investigation_does_not_resurrect_previous_visual_inputs(library, tool_name):
    descriptor = attach_visual_input({}, list(pair_rows()), library)["visual_input"]
    history = [message("human"), message("ai"), message("tool", descriptor), message("ai")]
    assert latest_visual_input([*history, message("tool", name=tool_name)]) is None
    assert latest_visual_input([message("human"), message("ai"), message("tool", descriptor,
        name=tool_name)]) == descriptor
