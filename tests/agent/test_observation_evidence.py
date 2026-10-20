"""Single-observation evidence separates pixels, metadata and saved predictions."""

import json

import pytest
from pydantic import ValidationError

from file_server.carrier_references import load_reference_library
from ship_agent.observation_evidence import build_observation_evidence
from ship_agent.reference_review import CarrierReferenceReview, reference_review_result
from tests.agent.test_reference_review import review
from tests.file_server.test_carrier_references import reference_folder
from tests.integration.test_missed_carrier_client import response_payload


@pytest.fixture
def library(tmp_path):
    return load_reference_library(reference_folder(tmp_path))


def evidence(row, library, **review_changes):
    reviewed = reference_review_result(row, review(library, **review_changes), library)
    return build_observation_evidence(row, reviewed, library)


@pytest.mark.parametrize("label,score,length", [("aircraft_carrier", .99, 220),
    ("not_aircraft_carrier", .4, 100), ("unknown", None, None)])
def test_question_13_accepts_observations_outside_14a_candidate_gate(library, label, score, length):
    row = response_payload()["ships"][0]
    row.update(classification=label, confidence=score, length_m=length)
    result = evidence(row, library)
    assert result["status"] == "complete" and result["measured_dimensions"]["length_m"] == length
    assert result["image_id"] == row["images"][0]["image_id"]
    assert result["image_url"] == row["images"][0]["url"]
    assert any(item["source"] == "image" for item in result["supporting_evidence"])
    assert result["saved_prediction"] == {"classification": label, "carrier_score": score}
    assert row["classification"] == label
    assert "flagged" not in result and "decision" not in result
    assert not result["is_ground_truth"] and not result["classifier_explanation_available"]
    assert "base64" not in json.dumps(result)


def test_model_output_is_distinct_from_independent_visual_evidence(library):
    row = response_payload()["ships"][0]
    result = evidence(row, library)
    assert result["comparison"] == "disagrees"
    assert {item["evidence_type"] for item in result["supporting_evidence"]} == {"reference_comparison"}
    assert {item["evidence_type"] for item in result["contradicting_evidence"]} == {"model_output"}
    assert result["reference_description"] == library.description


def test_specific_reference_differences_can_support_contrary_image_evidence(library):
    row = response_payload()["ships"][0]
    row["classification"] = "aircraft_carrier"
    result = evidence(row, library, assessment="not_aircraft_carrier",
        visible_features=["Các khối xếp hàng xuất hiện trên boong"],
        reference_evidence=[{"reference_id": library.images[0].reference_id,
                             "differences": ["Các khối trên boong khác bố cục trong ảnh mẫu"]}])
    assert result["comparison"] == "disagrees"
    assert any(item["source"] == "image" for item in result["contradicting_evidence"])
    assert any(item["source"] == "saved_prediction" for item in result["supporting_evidence"])


def test_mixed_visual_evidence_is_preserved(library):
    row = response_payload()["ships"][0]
    result = evidence(row, library, reference_evidence=[{
        "reference_id": library.images[0].reference_id,
        "similarities": ["Boong dài tương đồng"], "differences": ["Bố cục cấu trúc boong khác mẫu"]}])
    assert any(item["source"] == "image" for item in result["supporting_evidence"])
    assert any(item["source"] == "image" for item in result["contradicting_evidence"])


@pytest.mark.parametrize("quality", ["limited", "insufficient"])
def test_blur_is_unresolved_not_visual_counterevidence(library, quality):
    row = response_payload()["ships"][0]
    row.update(classification="unknown", confidence=None, length_m=None, width_m=None)
    result = evidence(row, library, image_quality=quality)
    assert result["comparison"] == "inconclusive"
    assert result["supporting_evidence"] == result["contradicting_evidence"] == []
    assert result["visual_review"]["assessment"] == "unknown"
    assert any("Thiếu số đo" in item for item in result["unresolved"])


def test_size_alone_is_never_classified_as_carrier_evidence(library):
    row = response_payload()["ships"][0]
    row.update(length_m=400, width_m=100, classification="unknown", confidence=None)
    result = evidence(row, library, assessment="unknown", visible_features=[], reference_evidence=[])
    assert result["supporting_evidence"] == result["contradicting_evidence"] == []
    assert result["measured_dimensions"] == {"length_m": 400, "width_m": 100}


def test_unsubstantiated_negative_is_unresolved(library):
    row = response_payload()["ships"][0]
    result = evidence(row, library, assessment="not_aircraft_carrier", visible_features=[], reference_evidence=[])
    assert result["comparison"] == "inconclusive" and result["visual_review"]["assessment"] == "unknown"
    assert not any(item["source"] == "image" for item in result["contradicting_evidence"])


def test_negative_without_cited_difference_is_inconclusive(library):
    row = response_payload()["ships"][0]
    result = evidence(row, library, assessment="not_aircraft_carrier", reference_evidence=[])
    assert result["comparison"] == "inconclusive"
    assert any("khác biệt cụ thể" in item for item in result["unresolved"])


@pytest.mark.parametrize("field", ["observation_id", "reference_revision"])
def test_evidence_from_another_observation_or_library_is_rejected(library, field):
    row = response_payload()["ships"][0]
    reviewed = reference_review_result(row, review(library), library)
    reviewed[field] = "wrong"
    with pytest.raises(ValueError, match="does not belong"):
        build_observation_evidence(row, reviewed, library)


def test_empty_reference_comparisons_and_positive_with_only_differences_rejected(library):
    with pytest.raises(ValidationError):
        review(library, reference_evidence=[{"reference_id": library.images[0].reference_id}])
    with pytest.raises(ValidationError):
        review(library, reference_evidence=[{"reference_id": library.images[0].reference_id,
                                             "differences": ["Some difference"]}])
