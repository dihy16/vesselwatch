"""Agreed negative-score/length candidate gates, scope and mandatory UTC dates."""

import pytest
from pydantic import ValidationError

from file_server.missed_carriers import MissedCarrierRequest, missed_carrier_candidates
from file_server.spatial import AreaGeometry
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def request(**kwargs):
    return MissedCarrierRequest(observed_from="2025-01-01", observed_to="2025-12-31", **kwargs)


def test_both_boundaries_inclusive_and_label_preserved_before_pagination():
    rows = [row("edge", 250, score=.01, label="not_aircraft_carrier", day="2025-01-01"),
            row("yes", 300, score=0, label="not_aircraft_carrier", day="2025-12-31"),
            row("short", 249.9, score=0, label="not_aircraft_carrier", day="2025-01-01"),
            row("score-above", 300, score=.01001, label="not_aircraft_carrier", day="2025-01-01"),
            row("positive-label", 300, score=0, day="2025-01-01"),
            row("missing-size", None, score=0, label="not_aircraft_carrier", day="2025-01-01"),
            row("missing-score", 300, score=None, label="not_aircraft_carrier", day="2025-01-01"),
            row("wrong-year", 300, score=0, label="not_aircraft_carrier", day="2026-01-01")]
    result = missed_carrier_candidates(rows, request(limit=1, offset=1))
    assert result["total"] == 2 and result["ships"][0]["observation_id"] == "yes"
    assert result["filters"]["carrier_score_lte"] == .01
    assert result["filters"]["min_length_m"] == 250


def test_space_optional_but_both_polygon_and_dates_apply_when_provided():
    rows = [row("inside", score=.001, label="not_aircraft_carrier", day="2025-10-01"),
            row("outside", score=.001, label="not_aircraft_carrier", day="2025-10-01", x=114),
            row("unlocated", score=.001, label="not_aircraft_carrier", day="2025-10-01", x=None, y=None)]
    assert missed_carrier_candidates(rows, request())["total"] == 3
    assert missed_carrier_candidates(rows, request(polygon=SQUARE), AreaGeometry(SQUARE))["total"] == 1


@pytest.mark.parametrize("values", [{}, {"observed_from": "2025-01-01"},
    {"observed_from": "", "observed_to": "2025-01-01"},
    {"observed_from": "2025-02-01", "observed_to": "2025-01-01"},
    {"observed_from": "2024-01-01", "observed_to": "2025-12-31"},
    {"observed_from": "2025-02-30", "observed_to": "2025-03-01"}])
def test_dates_required_and_invalid_ranges_rejected(values):
    with pytest.raises(ValidationError):
        MissedCarrierRequest(**values)


def test_cannot_override_agreed_score_or_length_gate_or_combine_regions():
    with pytest.raises(ValidationError):
        request(carrier_score_lte=.5)
    with pytest.raises(ValidationError):
        request(min_length_m=100)
    with pytest.raises(ValidationError):
        request(area_name="Biển Đông", polygon=SQUARE)
