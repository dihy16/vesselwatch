"""Both observations are evaluated against one library before explaining label differences."""

from copy import deepcopy
import json

import pytest

from file_server.carrier_references import load_reference_library
from ship_agent.pair_evidence import build_pair_evidence, validate_observation_pair
from ship_agent.reference_review import reference_review_result
from tests.agent.test_reference_review import review
from tests.file_server.test_carrier_references import reference_folder
from tests.integration.test_missed_carrier_client import response_payload


def pair_rows():
    first = response_payload()["ships"][0]
    first.update(observation_id="positive", ship_id="source-positive", classification="aircraft_carrier",
                 confidence=.95, length_m=300, width_m=60)
    first["images"][0].update(image_id="positive-image", url="http://localhost/images/positive-image")
    second = deepcopy(first)
    second.update(observation_id="negative", ship_id="source-negative", classification="not_aircraft_carrier",
                  confidence=.1, length_m=305, width_m=62)
    second["images"][0].update(image_id="negative-image", url="http://localhost/images/negative-image")
    return first, second


def reviewed(row, library, assessment, quality="sufficient"):
    changes = {"assessment": assessment, "image_quality": quality}
    if assessment == "not_aircraft_carrier":
        changes.update(visible_features=["Các khối hàng trên boong"], reference_evidence=[{
            "reference_id": library.images[0].reference_id,
            "differences": ["Bố cục các khối trên boong khác ảnh mẫu"]}])
    return reference_review_result(row, review(library, **changes), library)


@pytest.fixture
def library(tmp_path):
    return load_reference_library(reference_folder(tmp_path))


@pytest.mark.parametrize("first_assessment,second_assessment,outcome,explains", [
    ("aircraft_carrier", "not_aircraft_carrier", "visual_evidence_consistent_with_label_difference", True),
    ("aircraft_carrier", "aircraft_carrier", "visual_reviews_do_not_support_label_difference", False),
    ("not_aircraft_carrier", "not_aircraft_carrier", "visual_reviews_do_not_support_label_difference", False),
    ("not_aircraft_carrier", "aircraft_carrier", "visual_evidence_opposes_label_assignment", False),
    ("unknown", "not_aircraft_carrier", "inconclusive", False),
])
def test_outcome_comes_from_two_independent_reference_reviews(library, first_assessment, second_assessment, outcome, explains):
    first, second = pair_rows()
    result = build_pair_evidence(first, second, reviewed(first, library, first_assessment),
                                  reviewed(second, library, second_assessment), library)
    assert result["outcome"] == outcome and result["can_explain_label_difference"] is explains
    assert result["first_observation"]["observation_id"] == "positive"
    assert result["second_observation"]["observation_id"] == "negative"
    assert result["reference_revision"] == result["first_observation"]["reference_revision"] == result["second_observation"]["reference_revision"]
    assert not result["classifier_explanation_available"] and not result["is_same_vessel_established"]
    assert not result["is_ground_truth"] and "base64" not in json.dumps(result)
    assert first["classification"] == "aircraft_carrier" and second["classification"] == "not_aircraft_carrier"


@pytest.mark.parametrize("quality", ["limited", "insufficient"])
def test_one_blurry_image_cannot_explain_the_difference(library, quality):
    first, second = pair_rows()
    result = build_pair_evidence(first, second, reviewed(first, library, "aircraft_carrier"),
        reviewed(second, library, "not_aircraft_carrier", quality), library)
    assert result["outcome"] == "inconclusive" and not result["can_explain_label_difference"]
    assert result["second_observation"]["visual_review"]["assessment"] == "unknown"


@pytest.mark.parametrize("failure", ["same-id", "same-label", "unknown-label", "missing-length", "missing-width", "too-long", "too-wide"])
def test_pair_constraints_match_question_12(failure):
    first, second = pair_rows()
    if failure == "same-id":
        second["observation_id"] = first["observation_id"]
    elif failure == "same-label":
        second["classification"] = first["classification"]
    elif failure == "unknown-label":
        second["classification"] = "unknown"
    elif failure == "missing-length":
        second["length_m"] = None
    elif failure == "missing-width":
        second["width_m"] = None
    elif failure == "too-long":
        second["length_m"] = 400
    else:
        second["width_m"] = 80
    with pytest.raises(ValueError):
        validate_observation_pair(first, second)


def test_size_threshold_inclusive_symmetric_and_customizable():
    first, second = pair_rows()
    second.update(length_m=270, width_m=54)
    result = validate_observation_pair(first, second)
    assert result["length_difference_pct"] == result["width_difference_pct"] == 10
    assert validate_observation_pair(second, first) == result
    with pytest.raises(ValueError):
        validate_observation_pair(first, second, 9.99)
    second.update(length_m=300, width_m=60)
    assert validate_observation_pair(first, second, 0)["length_difference_pct"] == 0


def test_review_identity_and_reference_revision_cannot_be_mixed(library):
    first, second = pair_rows()
    first_reviewed = reviewed(first, library, "aircraft_carrier")
    second_reviewed = reviewed(second, library, "not_aircraft_carrier")
    with pytest.raises(ValueError):
        build_pair_evidence(first, second, second_reviewed, first_reviewed, library)
    second_reviewed["reference_revision"] = "0" * 64
    with pytest.raises(ValueError):
        build_pair_evidence(first, second, first_reviewed, second_reviewed, library)
