"""Positive-label audits filter the full date/area scope, without hidden score/size gates."""

import pytest
from pydantic import ValidationError

from file_server.schemas.reviews import FalseCarrierRequest
from file_server.services.false_carriers import false_carrier_candidates
from file_server.services.spatial import AreaGeometry
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def request(**kwargs):
    return FalseCarrierRequest(observed_from="2025-01-01", observed_to="2025-12-31", **kwargs)


def test_all_saved_positives_in_scope_count_before_pagination_even_without_measurements():
    rows = [row("small", 100, score=.5, day="2025-01-01"),
            row("large", 300, score=.99, day="2025-12-31"),
            row("missing", None, width=None, score=None, day="2025-10-01"),
            row("stored-label", 200, score=.001, day="2025-10-01"),
            row("negative", 300, score=.99, label="not_aircraft_carrier", day="2025-01-01"),
            row("unknown", 300, score=.99, label="unknown", day="2025-01-01"),
            row("wrong-year", 300, score=.99, day="2026-01-01")]
    result = false_carrier_candidates(rows, request(limit=1, offset=1))
    assert result["total"] == 4 and result["ships"][0]["observation_id"] == "missing"
    assert result["filters"]["classification"] == "aircraft_carrier"
    assert result["filters"]["min_length_m"] is None and result["filters"]["carrier_score_gt"] is None


def test_optional_area_and_unlocated_observations():
    rows = [row("inside", day="2025-06-01"), row("outside", x=114, day="2025-06-01"),
            row("unlocated", x=None, y=None, day="2025-06-01")]
    assert false_carrier_candidates(rows, request())["total"] == 3
    assert false_carrier_candidates(rows, request(polygon=SQUARE), AreaGeometry(SQUARE))["total"] == 1


@pytest.mark.parametrize("values", [{}, {"observed_from": "2025-01-01"},
    {"observed_from": "", "observed_to": "2025-12-31"},
    {"observed_from": "2025-02-30", "observed_to": "2025-12-31"},
    {"observed_from": "2025-12-31", "observed_to": "2025-01-01"}])
def test_mandatory_valid_dates(values):
    with pytest.raises(ValidationError):
        FalseCarrierRequest(**values)


@pytest.mark.parametrize("extra", [{"min_length_m": 250}, {"carrier_score_gte": .99},
                                  {"classification": "not_aircraft_carrier"}, {"area_name": "Biển Đông", "polygon": SQUARE}])
def test_cannot_silently_change_the_positive_audit_scope(extra):
    with pytest.raises(ValidationError):
        request(**extra)
