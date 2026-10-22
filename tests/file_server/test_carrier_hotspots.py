"""Full-source statistics and exact membership, independent of the local SciPy binary."""

from copy import deepcopy
from math import radians
import sys
from types import SimpleNamespace

import pytest

from file_server.services.carrier_hotspots import EARTH_RADIUS_KM
from file_server.schemas.reviews import HotspotClusterRequest
from file_server.services.carrier_hotspots import build_hotspot_report
from file_server.services.carrier_hotspots import dbscan_labels
from file_server.services.carrier_hotspots import hotspot_cluster_candidates
from file_server.schemas.reviews import FalseCarrierRequest
from file_server.services.spatial import AreaGeometry
from tests.file_server.test_observation_analysis import row
from tests.file_server.test_spatial import SQUARE


def scope(**kwargs):
    return FalseCarrierRequest(observed_from="2025-01-01", observed_to="2025-01-03", **kwargs)


def report(rows, **kwargs):
    return build_hotspot_report(rows, scope(**kwargs), source_snapshot_id="a" * 64)


def source_rows():
    return [row("a1", 299, score=.5, x=111, y=16, day="2025-01-01"),
            row("a2", 300, score=1, x=111.01, y=16, day="2025-01-03"),
            row("a3", None, width=None, score=None, x=111.02, y=16, day="2025-01-03"),
            row("b1", 320, score=.8, x=115, y=20, day="2025-01-01"),
            row("b2", 330, score=.9, x=115.01, y=20, day="2025-01-01"),
            row("noise", 200, score=.1, x=120, y=25, day="2025-01-01"),
            row("unlocated", 250, score=0, x=None, y=None, day="2025-01-01"),
            row("negative", label="not_aircraft_carrier", x=111, y=16, day="2025-01-01"),
            row("outside-date", x=111, y=16, day="2025-01-04")]


@pytest.fixture(autouse=True)
def stub_labels(monkeypatch):
    """Fixed cluster-engine results isolate statistics/filtering from sklearn tests."""
    import file_server.services.carrier_hotspots as carrier_hotspots
    groups = {"a1": 0, "a2": 0, "a3": 0, "b1": 1, "b2": 1, "a": 0, "b": 0}
    monkeypatch.setattr(carrier_hotspots, "dbscan_labels", lambda rows:
                        [groups.get(item["observation_id"], -1) for item in rows])


def test_sklearn_adapter_uses_latitude_longitude_radians_and_30km(monkeypatch):
    seen = {}
    class FakeDBSCAN:
        def __init__(self, **kwargs):
            seen.update(kwargs)
        def fit_predict(self, values):
            seen["coordinates"] = values
            return SimpleNamespace(tolist=lambda: [0, 0])
    cluster = SimpleNamespace(DBSCAN=FakeDBSCAN)
    monkeypatch.setitem(sys.modules, "sklearn", SimpleNamespace(cluster=cluster))
    monkeypatch.setitem(sys.modules, "sklearn.cluster", cluster)
    assert dbscan_labels([row("a", x=100, y=80), row("b", x=101, y=80)]) == [0, 0]
    assert seen["coordinates"] == [[radians(80), radians(100)], [radians(80), radians(101)]]
    assert seen["eps"] == 30 / EARTH_RADIUS_KM and seen["min_samples"] == 2
    assert seen["metric"] == "haversine" and seen["algorithm"] == "ball_tree"


def test_observation_ids_deduplicate_before_calling_cluster_engine(monkeypatch):
    import file_server.services.carrier_hotspots as carrier_hotspots
    seen = []
    monkeypatch.setattr(carrier_hotspots, "dbscan_labels", lambda rows: seen.extend(rows) or [-1] * len(rows))
    duplicate = row("same-id", x=111, y=16, day="2025-01-01")
    single, _ = report([duplicate, deepcopy(duplicate)])
    assert len(seen) == 1 and single["total_detections"] == single["noise_count"] == 1


def test_full_scope_counts_statistics_and_global_ranking_before_pagination():
    data, groups = report(source_rows(), limit=1)
    assert data["total"] == 2 and data["total_detections"] == 7
    assert data["located_count"] == 6 and data["missing_position_count"] == 1
    assert data["clustered_detection_count"] == 5 and data["noise_count"] == 1
    assert data["next_offset"] == 1 and len(data["clusters"]) == 1
    first = data["clusters"][0]
    assert first["rank"] == 1 and first["detection_count"] == 3
    assert [entry["count"] for entry in first["daily_stats"]] == [1, 0, 2]
    assert first["active_day_count"] == 2
    assert first["length_m"]["missing_count"] == 1 and first["width_m"]["missing_count"] == 1
    assert first["length_groups"] == {"below_300m": 1, "at_least_300m": 1, "missing": 1}
    assert first["carrier_score"]["mean"] == .75 and first["carrier_score"]["missing_count"] == 1
    assert first["carrier_score"]["histogram"][-1]["count"] == 1
    assert set(item["observation_id"] for item in groups[first["cluster_id"]]) == {"a1", "a2", "a3"}
    second, _ = report(source_rows(), limit=1, offset=1)
    assert second["clusters"][0]["detection_count"] == 2 and second["next_offset"] is None
    assert second["report_id"] == data["report_id"]
    assert second["summary"] == data["summary"]


def test_area_filter_runs_before_clustering_and_missing_coordinates_are_not_assigned_to_area():
    rows = [row("inside", x=111.99, y=16, day="2025-01-01"),
            row("outside", x=112.01, y=16, day="2025-01-01"),
            row("missing", x=None, y=None, day="2025-01-01")]
    data, _ = build_hotspot_report(rows, scope(polygon=SQUARE), source_snapshot_id="a" * 64,
                                   geometry=AreaGeometry(SQUARE))
    assert data["total_detections"] == data["located_count"] == data["noise_count"] == 1
    assert data["unlocated_in_date_range_count"] == 1 and data["missing_position_count"] == 0
    assert data["total"] == 0


def test_stable_ids_and_report_scope_binding():
    data, _ = report(source_rows())
    reordered, _ = report(list(reversed(source_rows())))
    assert data == reordered
    changed, _ = build_hotspot_report(source_rows(), scope(), source_snapshot_id="b" * 64)
    assert changed["report_id"] != data["report_id"]
    new_dates, _ = build_hotspot_report(source_rows(), FalseCarrierRequest(
        observed_from="2025-01-01", observed_to="2025-01-02"), source_snapshot_id="a" * 64)
    assert new_dates["report_id"] != data["report_id"]


def test_exact_members_are_prioritized_without_spatial_approximation():
    data, groups = report(source_rows())
    cluster_id = data["clusters"][0]["cluster_id"]
    request = HotspotClusterRequest(**scope(limit=1).model_dump(), report_id=data["report_id"], cluster_id=cluster_id)
    page = hotspot_cluster_candidates(groups[cluster_id], request)
    assert page["total"] == 3 and page["dimension_candidate_count"] == 1
    assert page["ships"][0]["observation_id"] == "a1"


def test_empty_and_missing_only_scopes_return_honest_statistics():
    data, groups = report([])
    assert data["total"] == 0 and data["summary"]["length_m"]["mean"] is None and groups == {}
    missing, _ = report([row("a", None, width=None, score=None, x=None, y=None, day="2025-01-01")])
    assert missing["missing_position_count"] == 1 and missing["located_count"] == 0
    assert missing["summary"]["geographic_extent"] is None and missing["total"] == 0


def test_date_line_bounds_do_not_describe_a_358_degree_area():
    data, _ = report([row("a", x=179.9, y=0, day="2025-01-01"), row("b", x=-179.9, y=0, day="2025-01-01")])
    extent = data["clusters"][0]["geographic_extent"]
    assert extent["crosses_antimeridian"] and extent["west"] == pytest.approx(179.9)
    assert extent["east"] == pytest.approx(-179.9)
