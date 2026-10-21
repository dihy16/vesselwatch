"""BR 19 reads every selected positive and groups only validated observation evidence."""

from copy import deepcopy

import pytest

from file_server.carrier_references import load_reference_library
from ship_agent.label_review import build_label_review, run_label_investigation
from tests.agent.test_false_carrier_evidence import visual
from tests.file_server.test_carrier_references import reference_folder
from tests.integration.test_label_review_client import payload


@pytest.fixture
def library(tmp_path):
    return load_reference_library(reference_folder(tmp_path))


@pytest.mark.parametrize("assessment,quality,group,flagged", [
    ("not_aircraft_carrier", "sufficient", "suspected_false_positive", True),
    ("aircraft_carrier", "sufficient", "reference_consistent", False),
    ("unknown", "sufficient", "inconclusive", False),
    ("not_aircraft_carrier", "limited", "insufficient_image", False),
    ("not_aircraft_carrier", "insufficient", "insufficient_image", False)])
def test_annotation_recommendations_require_clear_grounded_conflict(library, assessment, quality, group, flagged):
    row = payload()["ships"][0]
    before = deepcopy(row)
    item = build_label_review(row, visual(row, library, assessment, quality), library)
    assert item["review_group"] == group and item["flagged"] == flagged
    assert item["annotation_recommended"] == flagged and not item["label_applied"]
    assert row == before and not item["is_confirmed_error"] and not item["classifier_explanation_available"]
    if flagged:
        assert item["review_factors"][0]["reference_id"] == library.images[0].reference_id
        assert item["review_factors"][0]["details"]


def test_unsupported_negative_is_inconclusive_and_no_label_recommendation(library):
    row = payload()["ships"][0]
    result = visual(row, library)
    result["visual_review"]["visible_features"] = []
    item = build_label_review(row, result, library)
    assert item["review_group"] == "inconclusive" and not item["annotation_recommended"]


def test_all_five_groups_reconcile_page_scope_and_read_short_and_high_score_targets(library):
    candidates = payload()
    rows = [deepcopy(candidates["ships"][0]) for _ in range(5)]
    for index, row in enumerate(rows):
        row.update(observation_id=str(index), confidence=.5 + index * .1, length_m=100 if index == 0 else 350)
    rows[-1]["confidence"] = 1
    candidates.update(ships=rows, total=7, limit=5)
    seen = []
    def review(row, refs):
        seen.append(row["observation_id"])
        if row["observation_id"] == "4":
            raise RuntimeError("private-provider-body")
        return visual(row, refs, "aircraft_carrier" if row["observation_id"] == "1" else
                      "unknown" if row["observation_id"] == "2" else "not_aircraft_carrier",
                      "limited" if row["observation_id"] == "3" else "sufficient")
    result, _ = run_label_investigation(candidates, load_library=lambda: library, create_reviewer=lambda: review)
    assert seen == ["0", "1", "2", "3", "4"]
    assert set(result["group_counts"].values()) == {1} and sum(result["group_counts"].values()) == 5
    assert result["reviewed_count"] == 4 and result["failed_count"] == 1 and result["selected_count"] == 5
    assert result["annotation_candidate_count"] == 1 and len(result["annotation_candidates"]) == 1
    assert result["annotation_candidates"][0]["observation_id"] == "0"
    assert result["next_offset"] == 5 and not result["coverage_complete"]
    assert "private-provider-body" not in str(result)


@pytest.mark.parametrize("bad", ["identity", "reference", "citation"])
def test_unrelated_evidence_is_counted_as_failed_not_annotation_candidate(library, bad):
    candidates = payload()
    candidates.update(ships=candidates["ships"][:1], total=1)
    def review(row, refs):
        result = visual(row, refs)
        if bad == "identity":
            result["observation_id"] = "another"
        elif bad == "reference":
            result["reference_revision"] = "f" * 64
        else:
            result["visual_review"]["reference_evidence"][0]["reference_id"] = "f" * 32
        return result
    result, _ = run_label_investigation(candidates, load_library=lambda: library, create_reviewer=lambda: review)
    assert result["group_counts"]["review_failed"] == 1 and result["annotation_candidate_count"] == 0
    assert result["status"] == "failed" and not result["coverage_complete"]


@pytest.mark.parametrize("failed_step", ["library", "model"])
def test_missing_library_or_model_preserves_full_statistics_and_marks_unreviewed_errors(library, failed_step):
    candidates = payload()
    def unavailable():
        raise ValueError("private-configuration")
    result, _ = run_label_investigation(candidates,
        load_library=unavailable if failed_step == "library" else lambda: library,
        create_reviewer=unavailable if failed_step == "model" else lambda: pytest.fail("Library must load first"))
    assert result["candidate_statistics"] == candidates["candidate_statistics"]
    assert result["group_counts"]["review_failed"] == 3 and result["reviewed_count"] == 0
    assert result["annotation_candidates"] == [] and not result["reference_comparison_performed"]
    assert "private-configuration" not in str(result)


@pytest.mark.parametrize("total,offset,status", [(0, 0, "no_candidates"), (3, 3, "empty_page")])
def test_empty_scope_or_page_loads_no_reference_or_vision(total, offset, status):
    candidates = payload()
    candidates.update(ships=[], total=total, offset=offset)
    result, library = run_label_investigation(candidates,
        load_library=lambda: pytest.fail("No target images"), create_reviewer=lambda: pytest.fail("No target images"))
    assert result["status"] == status and library is None
    assert result["annotation_candidates"] == [] and sum(result["group_counts"].values()) == 0
