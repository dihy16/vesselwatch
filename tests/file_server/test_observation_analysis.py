"""Size/score boundaries and full-source comparisons, without services or LLMs."""

from copy import deepcopy
import random

import pytest
from pydantic import ValidationError

from file_server.schemas.area_models import AreaQueryInput
from file_server.schemas.area_models import ObservationAnalysisRequest
from file_server.services.observation_analysis import analysis_filters
from file_server.services.observation_analysis import analyze_observations
from file_server.services.spatial import AreaGeometry
from file_server.services.spatial import query_observations
from tests.file_server.test_spatial import observation, SQUARE


def row(identity, length=300, width=60, label="aircraft_carrier", score=.9, **kwargs):
    return {**observation(identity, length=length, label=label, **kwargs),
            "width_m": width, "confidence": score}


def test_question_9_default_rule_filters_dimensions_and_negative_label():
    rows = [row("min", 250, 50, "not_aircraft_carrier"), row("max", 350, 80, "not_aircraft_carrier"),
            row("short", 249, 60, "not_aircraft_carrier"), row("wide", 300, 81, "not_aircraft_carrier"),
            row("positive"), row("unknown", label="unknown", score=None),
            row("no-size", None, None, "not_aircraft_carrier")]
    request = ObservationAnalysisRequest(analysis="dimension_mismatch", limit=1, offset=1)
    result = analyze_observations(rows, request)
    assert result["total"] == 2 and result["count_unit"] == "detections"
    assert len(result["ships"]) == 1
    assert result["filters"]["classification"] == "not_aircraft_carrier"
    assert result["filters"]["min_length_m"] == 250 and result["filters"]["max_width_m"] == 80


def test_question_9_explicit_ranges_replace_defaults_for_that_dimension():
    request = ObservationAnalysisRequest(analysis="dimension_mismatch", min_length_m=400,
                                          min_width_m=20, max_width_m=40)
    filters = analysis_filters(request)
    assert filters.min_length_m == 400 and filters.max_length_m is None
    result = analyze_observations([row("a", 410, 30, "not_aircraft_carrier")], request)
    assert result["total"] == 1


def test_question_10_strict_length_and_carrier_score_before_pagination():
    rows = [row("yes"), row("length-edge", 250), row("score-edge", score=.8),
            row("negative", label="not_aircraft_carrier"), row("missing-score", score=None),
            row("missing-size", None)]
    query = AreaQueryInput(length_gt_m=250, carrier_score_gt=.8, classification="aircraft_carrier", limit=1)
    assert [r["observation_id"] for r in query_observations(rows, query)] == ["yes"]
    assert query_observations(rows, AreaQueryInput(carrier_score_gt=1)) == []


def test_question_12_counts_all_pairs_with_unique_stable_pagination():
    rows = [row("p1"), row("p2", 310, 62), row("n1", 305, 61, "not_aircraft_carrier"),
            row("n2", 300, 60, "not_aircraft_carrier"), row("wide", 300, 100, "not_aircraft_carrier"),
            row("unknown", label="unknown"), row("missing", None, 60, "not_aircraft_carrier")]
    request = ObservationAnalysisRequest(analysis="similar_dimensions", limit=1)
    result = analyze_observations(rows, request)
    assert result["total"] == 4 and len(result["pairs"]) == 1
    assert result["count_unit"] == "observation_pairs"
    assert result["excluded_unknown_classification_count"] == 1
    assert result["excluded_missing_dimensions_count"] == 1
    all_pairs = []
    for offset in range(4):
        page = analyze_observations(rows, request.model_copy(update={"offset": offset}))
        pair = page["pairs"][0]
        all_pairs.append((pair["aircraft_carrier"]["observation_id"], pair["not_aircraft_carrier"]["observation_id"]))
    assert len(set(all_pairs)) == 4
    shuffled = deepcopy(rows)
    random.Random(42).shuffle(shuffled)
    assert analyze_observations(shuffled, request) == result
    assert analyze_observations(rows, request.model_copy(update={"offset": 100}))["pairs"] == []


@pytest.mark.parametrize("tolerance,expected", [(0, 0), (9.99, 0), (10, 1), (100, 1)])
def test_similarity_is_symmetric_inclusive_and_applies_to_both_dimensions(tolerance, expected):
    rows = [row("p", 300, 60), row("n", 270, 54, "not_aircraft_carrier")]
    request = ObservationAnalysisRequest(analysis="similar_dimensions", similarity_tolerance_pct=tolerance)
    result = analyze_observations(rows, request)
    assert result["total"] == expected
    if expected:
        assert result["pairs"][0]["length_difference_pct"] == 10
        assert result["pairs"][0]["width_difference_pct"] == 10
    rows[0]["classification"], rows[1]["classification"] = rows[1]["classification"], rows[0]["classification"]
    assert analyze_observations(rows, request)["total"] == expected


def test_exact_sizes_pair_at_zero_tolerance_and_duplicate_observation_not_counted_twice():
    rows = [row("p"), row("p"), row("n", label="not_aircraft_carrier")]
    result = analyze_observations(rows, ObservationAnalysisRequest(analysis="similar_dimensions", similarity_tolerance_pct=0))
    assert result["total"] == 1


def test_both_members_must_match_dates_and_polygon():
    rows = [row("p"), row("n", label="not_aircraft_carrier"),
            row("outside", label="not_aircraft_carrier", x=114),
            row("old", label="not_aircraft_carrier", day="2025-01-01"),
            row("unlocated", label="not_aircraft_carrier", x=None, y=None)]
    request = ObservationAnalysisRequest(analysis="similar_dimensions", observed_from="2026-10-01", observed_to="2026-10-01")
    assert analyze_observations(rows, request, AreaGeometry(SQUARE))["total"] == 1


@pytest.mark.parametrize("values", [
    {"similarity_tolerance_pct": -1}, {"similarity_tolerance_pct": float("nan")},
    {"carrier_score_gt": float("inf")}, {"carrier_score_gt": 1.1},
    {"min_length_m": 400, "max_length_m": 300}, {"classification": "aircraft_carrier"},
])
def test_invalid_comparison_parameters_are_errors(values):
    with pytest.raises(ValidationError):
        ObservationAnalysisRequest(analysis="similar_dimensions", **values)


def test_mismatch_rejects_positive_classification():
    with pytest.raises(ValidationError):
        ObservationAnalysisRequest(analysis="dimension_mismatch", classification="aircraft_carrier")
