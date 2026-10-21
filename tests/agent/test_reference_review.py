"""All-reference pixel payloads, evidence gates and truthful partial-review reporting."""

import base64
import json

import pytest
from pydantic import ValidationError

from file_server.media.carrier_references import load_reference_library
from ship_agent.vision.schemas import CarrierReferenceReview
from ship_agent.workflows.reference_review import reference_review_content
from ship_agent.workflows.reference_review import reference_review_result
from ship_agent.workflows.reference_review import run_reference_reviews
from tests.file_server.test_carrier_references import png, reference_folder


@pytest.fixture
def library(tmp_path):
    reference_folder(tmp_path)
    (tmp_path / "second.png").write_bytes(png("red"))
    return load_reference_library(tmp_path)


def observation(identity="one"):
    return {"observation_id": identity, "ship_id": "source-" + identity,
            "classification": "not_aircraft_carrier", "confidence": .001,
            "images": [{"url": "http://public/images/" + identity}]}


def review(library, **changes):
    return CarrierReferenceReview.model_validate({"image_quality": "sufficient", "assessment": "aircraft_carrier",
        "visible_features": ["Boong phẳng dài, có cấu trúc lệch bên"],
        "reference_evidence": [{"reference_id": library.images[0].reference_id,
                                "similarities": ["Boong và cấu trúc lệch bên cùng hiện rõ"]}],
        "limitations": [], "reasoning": "Các chi tiết nhìn thấy phù hợp bộ mẫu.", **changes})


def test_pixel_payload_has_exactly_target_and_every_reference(library):
    target = png("green")
    content = reference_review_content(target, library)
    pixels = [base64.b64decode(item["image_url"]["url"].split(",", 1)[1])
              for item in content if item["type"] == "image_url"]
    assert pixels == [target] + [image.data for image in library.images]
    assert library.description in json.dumps(content, ensure_ascii=False)
    assert all(image.reference_id in json.dumps(content) for image in library.images)
    assert "not_aircraft_carrier" not in json.dumps(content)


@pytest.mark.parametrize("quality,assessment,decision", [
    ("sufficient", "aircraft_carrier", "flagged"),
    ("limited", "aircraft_carrier", "insufficient_image"),
    ("insufficient", "aircraft_carrier", "insufficient_image"),
    ("sufficient", "not_aircraft_carrier", "not_flagged"),
    ("sufficient", "unknown", "inconclusive"),
])
def test_only_clear_positive_evidence_flags_without_changing_saved_label(library, quality, assessment, decision):
    row = observation()
    result = reference_review_result(row, review(library, image_quality=quality, assessment=assessment), library)
    assert result["decision"] == decision and result["flagged"] == (decision == "flagged")
    assert result["saved_prediction"]["classification"] == row["classification"] == "not_aircraft_carrier"
    if quality != "sufficient":
        assert result["visual_review"]["assessment"] == "unknown"
    assert "base64" not in json.dumps(result) and not result["is_ground_truth"]


@pytest.mark.parametrize("changes", [{"visible_features": []}, {"reference_evidence": []}])
def test_unsupported_positive_provider_output_is_error(library, changes):
    with pytest.raises(ValidationError):
        review(library, **changes)


def test_hallucinated_reference_citation_rejected(library):
    result = review(library, reference_evidence=[{"reference_id": "0" * 32, "similarities": ["unsupported"]}])
    with pytest.raises(ValueError, match="unknown reference"):
        reference_review_result(observation(), result, library)


def test_partial_coverage_and_failures_are_not_global_no_flags(library):
    rows = [observation("flag"), observation("blur"), observation("error")]
    candidates = {"ships": rows, "total": 5, "offset": 0, "limit": 3, "filters": {}, "source_snapshot_id": "snapshot"}
    def inspect(row, refs):
        if row["observation_id"] == "error":
            raise RuntimeError("secret-provider-payload-must-not-leak")
        return reference_review_result(row, review(refs, image_quality="insufficient" if row["observation_id"] == "blur" else "sufficient"), refs)
    result = run_reference_reviews(candidates, library, inspect)
    assert result["status"] == "partial" and not result["coverage_complete"]
    assert result["reviewed_count"] == 2 and result["failed_count"] == 1 and result["next_offset"] == 3
    assert result["flagged_count"] == 1 and len(result["flags"]) == 1
    assert result["unflagged"][0]["decision"] == "insufficient_image"
    assert "secret-provider" not in json.dumps(result) and "base64" not in json.dumps(result)


def test_all_failed_is_failed_and_all_clear_negatives_can_complete(library):
    candidates = {"ships": [observation()], "total": 1, "offset": 0, "limit": 20, "filters": {}}
    def fail(*_):
        raise RuntimeError("provider failed")
    failed = run_reference_reviews(candidates, library, fail)
    assert failed["status"] == "failed" and not failed["coverage_complete"]
    complete = run_reference_reviews(candidates, library, lambda row, refs:
        reference_review_result(row, review(refs, assessment="not_aircraft_carrier"), refs))
    assert complete["status"] == "complete" and complete["coverage_complete"]
    assert complete["flagged_count"] == 0 and complete["reviewed_count"] == 1


def test_orchestrator_does_not_accept_blurry_image_flag(library):
    candidates = {"ships": [observation()], "total": 1, "offset": 0, "limit": 20, "filters": {}}
    def incorrect(row, refs):
        result = reference_review_result(row, review(refs, image_quality="insufficient"), refs)
        return {**result, "flagged": True, "decision": "flagged"}
    result = run_reference_reviews(candidates, library, incorrect)
    assert result["status"] == "failed" and result["flagged_count"] == 0
