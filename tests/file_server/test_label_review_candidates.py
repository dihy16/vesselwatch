"""BR 19 orders all scoped positives by score before selecting a review page."""

from copy import deepcopy

from file_server.schemas.reviews import FalseCarrierRequest
from file_server.services.label_review import label_review_candidates
from file_server.services.spatial import AreaGeometry
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def scope(**kwargs):
    return FalseCarrierRequest(observed_from="2025-01-01", observed_to="2025-12-31", **kwargs)


def source_rows():
    return [row("high", 100, score=1, day="2025-01-01"),
            row("low", None, width=None, score=.5, day="2025-12-31"),
            row("middle", 400, score=.8, day="2025-06-01"),
            row("missing", 350, score=None, day="2025-01-01"),
            row("stored-positive", 200, score=0, day="2025-01-01"),
            row("negative", label="not_aircraft_carrier", score=.55, day="2025-01-01"),
            row("unknown", label="unknown", score=None, day="2025-01-01"),
            row("outside-date", score=.6, day="2026-01-01")]


def test_global_score_order_keeps_high_missing_and_below_threshold_positive_scores():
    rows = source_rows()
    rows.append(deepcopy(rows[1]))
    before = deepcopy(rows)
    ids = []
    for offset in range(5):
        page = label_review_candidates(rows, scope(limit=1, offset=offset))
        assert page["total"] == 5 and page["candidate_statistics"]["detection_count"] == 5
        assert page["candidate_statistics"]["carrier_score"]["missing_count"] == 1
        ids.append(page["ships"][0]["observation_id"])
    assert ids == ["stored-positive", "low", "middle", "high", "missing"]
    assert rows == before


def test_area_filter_and_missing_coordinates_before_score_order():
    rows = source_rows() + [row("outside", x=114, score=.01, day="2025-01-01"),
                            row("unlocated", x=None, y=None, score=.02, day="2025-01-01")]
    assert label_review_candidates(rows, scope())["total"] == 7
    result = label_review_candidates(rows, scope(polygon=SQUARE), AreaGeometry(SQUARE))
    assert result["total"] == 5 and result["ships"][0]["observation_id"] == "stored-positive"


def test_ties_are_stable_by_time_then_observation_id_and_empty_page_retains_statistics():
    rows = [row("b", score=.5, day="2025-01-01"), row("a", score=.5, day="2025-01-01")]
    assert [item["observation_id"] for item in label_review_candidates(rows, scope())["ships"]] == ["a", "b"]
    empty = label_review_candidates(rows, scope(offset=5))
    assert empty["ships"] == [] and empty["total"] == 2 and empty["candidate_statistics"]["detection_count"] == 2
