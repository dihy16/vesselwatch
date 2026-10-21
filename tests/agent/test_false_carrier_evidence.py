"""Only clear, cited non-carrier evidence flags a saved carrier-positive observation."""

from copy import deepcopy

import pytest

from file_server.carrier_references import load_reference_library
from ship_agent.false_carrier_evidence import build_false_carrier_evidence
from ship_agent.reference_review import run_reference_reviews
from tests.agent.test_pair_evidence import reviewed
from tests.file_server.test_carrier_references import reference_folder
from tests.integration.test_false_carrier_client import positive_payload


@pytest.fixture
def library(tmp_path):
    return load_reference_library(reference_folder(tmp_path))


def visual(row, library, assessment="not_aircraft_carrier", quality="sufficient"):
    result = reviewed(row, library, assessment, quality)
    if assessment == "not_aircraft_carrier":
        result["visual_review"]["visible_features"] = ["Đường bao thân gần chữ nhật, bề rộng tương đối đều"]
        result["visual_review"]["reference_evidence"][0]["differences"] = ["Đường bao TARGET ít thuôn hơn mẫu"]
    return result


@pytest.mark.parametrize("assessment,quality,decision", [
    ("not_aircraft_carrier", "sufficient", "flagged"),
    ("aircraft_carrier", "sufficient", "not_flagged"),
    ("unknown", "sufficient", "inconclusive"),
    ("not_aircraft_carrier", "limited", "insufficient_image"),
    ("not_aircraft_carrier", "insufficient", "insufficient_image"),
])
def test_only_grounded_negative_review_flags_and_preserves_original_prediction(library, assessment, quality, decision):
    row = positive_payload()["ships"][0]
    before = deepcopy(row)
    result = build_false_carrier_evidence(row, visual(row, library, assessment, quality), library)
    assert result["decision"] == decision and result["flagged"] == (decision == "flagged")
    assert result["saved_prediction"] == {"classification": "aircraft_carrier", "carrier_score": .5}
    assert row == before and not result["is_confirmed_error"] and not result["is_ground_truth"]
    if decision == "flagged":
        assert result["comparison"] == "disagrees" and result["contradicting_evidence"]
        assert result["flag_reason"] == "suspected_non_carrier"


@pytest.mark.parametrize("missing", ["visible_features", "differences"])
def test_unsupported_negative_is_unknown_not_a_flag(library, missing):
    row = positive_payload()["ships"][0]
    result = visual(row, library)
    if missing == "visible_features":
        result["visual_review"]["visible_features"] = []
    else:
        result["visual_review"]["reference_evidence"][0]["differences"] = []
        result["visual_review"]["reference_evidence"][0]["similarities"] = ["Dáng thuôn dài"]
    evidence = build_false_carrier_evidence(row, result, library)
    assert evidence["decision"] == "inconclusive" and evidence["visual_review"]["assessment"] == "unknown"
    assert not evidence["flagged"]


@pytest.mark.parametrize("failure", ["negative-label", "wrong-observation", "wrong-revision", "unknown-citation"])
def test_cannot_flag_unrelated_or_unregistered_evidence(library, failure):
    row = positive_payload()["ships"][0]
    result = visual(row, library)
    if failure == "negative-label":
        row["classification"] = "not_aircraft_carrier"
    elif failure == "wrong-observation":
        result["observation_id"] = "other"
    elif failure == "wrong-revision":
        result["reference_revision"] = "0" * 64
    else:
        result["visual_review"]["reference_evidence"][0]["reference_id"] = "0" * 32
    with pytest.raises(ValueError):
        build_false_carrier_evidence(row, result, library)


def test_page_accounting_preserves_flags_insufficient_errors_and_partial_coverage(library):
    candidates = positive_payload()
    rows = [deepcopy(candidates["ships"][0]) for _ in range(4)]
    for index, row in enumerate(rows):
        row["observation_id"] = str(index)
    candidates.update(ships=rows, total=8, limit=4)
    def compare(row, refs):
        if row["observation_id"] == "3":
            raise ValueError("secret-provider-body")
        return visual(row, refs, "aircraft_carrier" if row["observation_id"] == "1" else "not_aircraft_carrier",
                      "limited" if row["observation_id"] == "2" else "sufficient")
    result = run_reference_reviews(candidates, library, compare, result_builder=build_false_carrier_evidence)
    assert result["flagged_count"] == 1 and result["reviewed_count"] == 3 and result["failed_count"] == 1
    assert result["next_offset"] == 4 and not result["coverage_complete"]
    assert {r["decision"] for r in result["unflagged"]} == {"not_flagged", "insufficient_image"}
    assert "secret-provider-body" not in str(result)


def test_invalid_raw_review_is_still_rejected_before_the_result_builder(library):
    candidates = positive_payload()
    def compare(row, refs):
        result = visual(row, refs)
        result["flagged"] = True  # Raw negative review is not a missed-carrier flag.
        return result
    result = run_reference_reviews(candidates, library, compare, result_builder=build_false_carrier_evidence)
    assert result["status"] == "failed" and result["flagged_count"] == 0 and result["failed_count"] == 1
