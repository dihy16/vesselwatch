"""BR 17 ranks the complete, filtered scope before any pagination."""

from copy import deepcopy

from file_server.services.carrier_investigation import carrier_investigation_candidates
from file_server.services.carrier_investigation import dimension_priority
from file_server.schemas.reviews import FalseCarrierRequest
from file_server.services.spatial import AreaGeometry
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def test_global_priority_order_boundary_dedup_and_scope():
    rows = [row("long", 301, day="2025-01-01"), row("edge", 300, day="2025-01-01"),
            row("short", 299.9, day="2025-12-31"), row("missing", None, day="2025-01-01"),
            row("negative", 100, label="not_aircraft_carrier", day="2025-01-01"),
            row("old", 100, day="2024-12-31"), row("outside", 100, x=114, day="2025-01-01"),
            row("unlocated", 100, x=None, y=None, day="2025-01-01")]
    rows.append(deepcopy(rows[2]))
    scope = dict(observed_from="2025-01-01", observed_to="2025-12-31", polygon=SQUARE, limit=1)
    ids = []
    for offset in range(4):
        result = carrier_investigation_candidates(list(reversed(rows)), FalseCarrierRequest(**scope, offset=offset),
                                                   AreaGeometry(SQUARE))
        assert result["total"] == 4 and result["dimension_candidate_count"] == 1
        assert result["visual_candidate_count"] == 3 and result["length_threshold_m"] == 300
        ids.append(result["ships"][0]["observation_id"])
    assert ids == ["short", "edge", "long", "missing"]


def test_missing_or_invalid_lengths_never_auto_prioritized():
    for value in [None, 0, -5, float("nan"), float("inf"), True, "250", 300, 300.01]:
        assert not dimension_priority({"length_m": value})
    assert dimension_priority({"length_m": 299.99})
    assert dimension_priority({"length_m": .1})


def test_without_area_unlocated_positives_and_missing_scores_still_included():
    scope = FalseCarrierRequest(observed_from="2025-01-01", observed_to="2025-12-31", offset=3)
    result = carrier_investigation_candidates([row("a", 100, score=None, x=None, y=None, day="2025-01-01")], scope)
    assert result["total"] == 1 and result["dimension_candidate_count"] == 1 and result["ships"] == []
