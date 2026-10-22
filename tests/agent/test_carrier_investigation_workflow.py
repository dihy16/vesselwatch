"""Priority 1 never reads pixels; priority 2 requires validated, clear non-carrier evidence."""

from copy import deepcopy

import pytest

from file_server.media.carrier_references import load_reference_library
from file_server.services.carrier_investigation import dimension_priority
from ship_agent.workflows.carrier_investigation import run_carrier_investigation
from tests.agent.test_false_carrier_evidence import visual
from tests.file_server.test_carrier_references import reference_folder
from tests.integration.test_carrier_investigation_client import investigation_payload


def candidates(lengths):
    payload = investigation_payload()
    base = payload["ships"][0]
    rows = []
    for index, length in enumerate(lengths):
        item = deepcopy(base)
        item.update(observation_id=str(index), length_m=length)
        rows.append(item)
    short = sum(dimension_priority(row) for row in rows)
    return {**payload, "ships": rows, "total": len(rows), "dimension_candidate_count": short,
            "visual_candidate_count": len(rows) - short}


def forbidden():
    pytest.fail("Dimension screening must not initialize/download references or vision")


def test_all_short_flags_without_loading_library_or_model_and_no_prediction_change():
    page = candidates([299.99, 100])
    before = deepcopy(page)
    result, library = run_carrier_investigation(page, load_library=forbidden, create_reviewer=forbidden)
    assert page == before and library is None
    assert result["coverage_complete"] and result["priority_1_count"] == 2
    assert result["reviewed_count"] == 0 and result["processed_count"] == 2
    assert not result["reference_comparison_performed"]
    assert all(item["priority"] == 1 and item["visual_review"] is None
               and not item["reference_comparison_performed"] and not item["is_confirmed_error"]
               and item["saved_prediction"]["classification"] == "aircraft_carrier"
               for item in result["flags"])


def test_exact_boundary_and_missing_size_read_images_but_short_never_does(tmp_path):
    library = load_reference_library(reference_folder(tmp_path))
    seen = []
    page = candidates([299, 300, None, 400, 350, 320])
    def review(row, refs):
        seen.append(row["observation_id"])
        assert refs is library
        if row["observation_id"] == "5":
            raise RuntimeError("secret-provider-body")
        return visual(row, refs,
                      "aircraft_carrier" if row["observation_id"] == "3" else "not_aircraft_carrier",
                      "limited" if row["observation_id"] == "4" else "sufficient")
    result, _ = run_carrier_investigation(page, load_library=lambda: library, create_reviewer=lambda: review)
    assert seen == ["1", "2", "3", "4", "5"]
    assert [item["priority"] for item in result["flags"]] == [1, 2, 2]
    assert result["priority_1_count"] == 1 and result["priority_2_count"] == 2
    assert result["reviewed_count"] == 4 and result["processed_count"] == 5
    assert result["failed_count"] == 1 and not result["coverage_complete"] and result["status"] == "partial"
    assert {item["decision"] for item in result["unflagged"]} == {"not_flagged", "insufficient_image"}
    assert "secret-provider-body" not in str(result)


@pytest.mark.parametrize("failed_step", ["library", "model"])
def test_preparation_failure_preserves_dimension_flags_and_reports_unread_images(tmp_path, failed_step):
    library = load_reference_library(reference_folder(tmp_path))
    def failed():
        raise ValueError("secret-provider-body")
    result, _ = run_carrier_investigation(candidates([100, 300, None]),
        load_library=failed if failed_step == "library" else lambda: library,
        create_reviewer=failed)
    assert result["priority_1_count"] == 1 and result["priority_2_count"] == 0
    assert result["failed_count"] == 2 and result["reviewed_count"] == 0
    assert result["status"] == "partial" and not result["coverage_complete"]
    assert not result["reference_comparison_performed"] and "secret-provider-body" not in str(result)


def test_all_failed_images_do_not_become_clean_negatives():
    def failed():
        raise RuntimeError("secret")
    result, _ = run_carrier_investigation(candidates([300]), load_library=failed, create_reviewer=forbidden)
    assert result["status"] == "failed" and result["failed_count"] == 1
    assert result["flagged_count"] == 0 and not result["coverage_complete"]


@pytest.mark.parametrize("total,offset,status,complete", [(0, 0, "no_candidates", True),
                                                       (5, 5, "empty_page", False)])
def test_empty_page_does_not_load_images_or_claim_full_coverage(total, offset, status, complete):
    page = candidates([])
    page.update(total=total, offset=offset, visual_candidate_count=total)
    result, _ = run_carrier_investigation(page, load_library=forbidden, create_reviewer=forbidden)
    assert result["status"] == status and result["coverage_complete"] == complete


def test_partial_dimension_page_reports_full_scope_counts_and_continuation():
    page = candidates([100, 200])
    page.update(total=5, dimension_candidate_count=3, visual_candidate_count=2, limit=2)
    result, _ = run_carrier_investigation(page, load_library=forbidden, create_reviewer=forbidden)
    assert result["next_offset"] == 2 and result["status"] == "partial"
    assert result["dimension_candidate_count"] == 3 and result["priority_1_count"] == 2
    assert not result["coverage_complete"]


def test_unsupported_negative_is_unknown_and_bad_citations_fail(tmp_path):
    library = load_reference_library(reference_folder(tmp_path))
    def review(row, refs):
        result = visual(row, refs)
        if row["observation_id"] == "0":
            result["visual_review"]["visible_features"] = []
        else:
            result["visual_review"]["reference_evidence"][0]["reference_id"] = "0" * 32
        return result
    result, _ = run_carrier_investigation(candidates([300, 301]), load_library=lambda: library,
                                         create_reviewer=lambda: review)
    assert result["priority_2_count"] == 0 and result["failed_count"] == 1
    assert result["unflagged"][0]["decision"] == "inconclusive"
