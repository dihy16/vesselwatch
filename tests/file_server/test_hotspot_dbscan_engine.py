"""Actual sklearn spatial clustering; requires a compatible NumPy/SciPy environment."""

from copy import deepcopy
from math import degrees

import pytest

pytest.importorskip("sklearn")

from file_server.services.carrier_hotspots import EARTH_RADIUS_KM
from file_server.services.carrier_hotspots import dbscan_labels
from file_server.services.carrier_hotspots import build_hotspot_report
from file_server.schemas.reviews import FalseCarrierRequest
from tests.file_server.test_observation_analysis import row


@pytest.mark.parametrize("distance,clustered", [(29.99, True), (30.01, False)])
def test_kilometer_boundary(distance, clustered):
    longitude = degrees(distance / EARTH_RADIUS_KM)
    labels = dbscan_labels([row("a", x=0, y=0), row("b", x=longitude, y=0)])
    assert (labels[0] == labels[1] != -1) is clustered
    if not clustered:
        assert labels == [-1, -1]


def test_density_chain_spans_more_than_eps():
    assert dbscan_labels([row("a", x=0, y=0), row("b", x=.2, y=0), row("c", x=.4, y=0)]) == [0, 0, 0]


@pytest.mark.parametrize("positions", [[(179.9, 0), (-179.9, 0)], [(100, 80), (101, 80)]])
def test_date_line_and_high_latitudes(positions):
    assert dbscan_labels([row(str(i), x=x, y=y) for i, (x, y) in enumerate(positions)]) == [0, 0]


def test_distinct_observations_at_identical_positions_count_toward_min_samples():
    duplicate = row("same-id", x=111, y=16, day="2025-01-01")
    scope = FalseCarrierRequest(observed_from="2025-01-01", observed_to="2025-01-03")
    single, _ = build_hotspot_report([duplicate, deepcopy(duplicate)], scope, source_snapshot_id="a" * 64)
    assert single["total_detections"] == single["noise_count"] == 1 and single["total"] == 0
    other = {**duplicate, "observation_id": "different-id", "observed_date": "2025-01-03",
             "observed_at": "2025-01-03T01:00:00+00:00"}
    clustered, _ = build_hotspot_report([duplicate, other], scope, source_snapshot_id="a" * 64)
    assert clustered["total"] == 1 and clustered["clusters"][0]["detection_count"] == 2
