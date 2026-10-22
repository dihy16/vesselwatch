"""Distance-based area queries use square bounds and retain their exact extent."""

from math import asin, cos, radians, sin, sqrt

from pydantic import ValidationError
import pytest

from file_server.schemas.area_models import AreaQueryInput, AreaRequest
from file_server.services.spatial import AREA_CENTERS, AreaGeometry, named_center, square_polygon


def distance_nm(a, b):
    lat1, lat2 = radians(a[1]), radians(b[1])
    value = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin(radians(b[0] - a[0]) / 2) ** 2
    return 6371008.8 * 2 * asin(sqrt(value)) / 1852


@pytest.mark.parametrize("latitude", [0, 18.221, 35.73525, -35])
def test_twenty_nm_means_twenty_per_direction_and_includes_corners(latitude):
    geometry = square_polygon(latitude, 110, 20)
    ring = geometry["coordinates"][0]
    west, south = ring[0]
    east, north = ring[2]
    assert (west + east) / 2 == pytest.approx(110)
    assert (south + north) / 2 == pytest.approx(latitude)
    for point in [(110, south), (110, north), (west, latitude), (east, latitude)]:
        assert distance_nm((110, latitude), point) == pytest.approx(20, rel=1e-5)
    area = AreaGeometry(geometry)
    assert distance_nm((110, latitude), (east, north)) > 28
    assert area.covers(east, north)  # A circular query would exclude this corner.
    assert area.covers(110, latitude)
    assert not area.covers(east + .001, latitude)


@pytest.mark.parametrize("name,key", [("căn cứ Thanh Đảo", "thanh_dao"), ("Qingdao", "thanh_dao"),
    ("can_cu_du_lam", "du_lam"), ("khu vực căn cứ Du Lâm", "du_lam"),
    ("Du Lâm Đông", "long_pha"), ("Longpo", "long_pha")])
def test_explicit_center_aliases(name, key):
    assert named_center(name) == key
    assert AreaQueryInput(area_name=name, radius_nm=20).radius_nm == 20


@pytest.mark.parametrize("payload", [
    {"area_name": "Thanh Đảo"}, {"radius_nm": 20},
    {"area_name": "Biển Đông", "radius_nm": 20}, {"area_name": "không biết", "radius_nm": 20},
    {"center_latitude": 18, "radius_nm": 20},
    {"center_latitude": 18, "center_longitude": 109},
    {"center_latitude": 18, "center_longitude": 109, "area_name": "Du Lâm", "radius_nm": 20},
    {"area_id": "a" * 32, "radius_nm": 20},
    *[{"area_name": "Du Lâm", "radius_nm": value} for value in (0, -20, float("nan"), float("inf"))],
    {"center_latitude": 89.9, "center_longitude": 0, "radius_nm": 20},
    {"center_latitude": 0, "center_longitude": 179.9, "radius_nm": 20},
])
def test_invalid_or_ambiguous_square_is_never_an_unbounded_query(payload):
    with pytest.raises(ValidationError):
        AreaQueryInput(**payload)


def test_square_and_explicit_polygon_are_exclusive():
    with pytest.raises(ValidationError):
        AreaRequest(area_name="Du Lâm", radius_nm=20, polygon=square_polygon(18, 109, 20))


@pytest.mark.parametrize("kind", ["missed", "positive", "monitoring"])
@pytest.mark.parametrize("area", [{"area_name": "Du Lâm", "radius_nm": 20},
    {"center_latitude": 18.221, "center_longitude": 109.537, "radius_nm": 20}])
def test_review_query_builders_preserve_base_or_coordinate_scope(kind, area):
    from file_server.schemas.reviews import MissedCarrierRequest, FalseCarrierRequest
    from file_server.schemas.monitoring import MonitoringRequest
    from file_server.services.missed_carriers import candidate_query as missed_query
    from file_server.services.false_carriers import candidate_query as positive_query
    from file_server.services.monitoring_reports import monitoring_query

    schema, builder = {"missed": (MissedCarrierRequest, missed_query),
                       "positive": (FalseCarrierRequest, positive_query),
                       "monitoring": (MonitoringRequest, monitoring_query)}[kind]
    result = builder(schema(observed_from="2025-01-01", observed_to="2025-12-31", **area))
    assert all(getattr(result, key) == value for key, value in area.items())
    assert result.observed_from == "2025-01-01" and result.polygon is None


def test_api_square_reuse_preview_handoff_and_redraw(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from file_server.api import area_queries
    import file_server.services.carrier_hotspots as hotspots
    from tests.file_server.test_spatial import SQUARE, observation

    center = AREA_CENTERS["thanh_dao"]
    lat, lon = center["latitude"], center["longitude"]
    ring = square_polygon(lat, lon, 20)["coordinates"][0]
    rows = [observation("center", x=lon, y=lat),
            observation("corner", x=ring[2][0], y=ring[2][1]),
            observation("outside", x=ring[2][0] + .01, y=lat)]
    app = FastAPI()
    area_queries.register_area_routes(app, observations=lambda request: rows,
        public_url=lambda request: "http://viewer", storage_root=lambda: tmp_path, source="demo")
    called = []

    async def answer(query, **kwargs):
        called.append(query)
        return "2 lượt phát hiện"

    monkeypatch.setattr(area_queries, "ask_area_agent", answer)
    monkeypatch.setattr(hotspots, "dbscan_labels", lambda rows: [0] * len(rows))
    with TestClient(app) as client:
        result = client.post("/area-queries", json={"area_name": "Thanh Đảo", "radius_nm": 20, "limit": 1}).json()
        assert result["status"] == "complete" and result["total"] == 2
        assert len(result["ships"]) == 1 and result["square_area"]["side_nm"] == 40
        assert client.get(f"/area-queries/{result['area_id']}").status_code == 200
        preview = client.get("/query-areas/thanh_dao?radius_nm=20").json()
        assert preview["geometry"] == square_polygon(lat, lon, 20)
        assert client.get("/query-areas/du_lam").status_code == 422
        assert client.get("/query-areas/du_lam?radius_nm=-1").status_code == 422
        page = client.post("/area-queries", json={"area_id": result["area_id"], "limit": 1, "offset": 1}).json()
        assert page["total"] == 2 and page["ships"] != result["ships"]
        assert page["square_area"] == result["square_area"]
        custom = client.post("/area-queries", json={"center_latitude": lat, "center_longitude": lon, "radius_nm": 20}).json()
        assert custom["total"] == 2
        assert client.post(f"/area-queries/{result['area_id']}/answer", json={}).status_code == 200
        AreaQueryInput.model_validate(called[0])
        assert called[0]["area_id"] == result["area_id"] and called[0]["radius_nm"] is None
        redrawn = client.post(f"/area-queries/{result['area_id']}/confirm", json={"polygon": SQUARE}).json()
        assert redrawn["square_area"] is None and redrawn["filters"]["radius_nm"] is None
        assert redrawn["total"] == 0
        for payload in ({"area_name": "Du Lâm"}, {"area_name": "unknown", "radius_nm": 20}):
            assert client.post("/area-queries", json=payload).status_code == 422
        analysis = client.post("/observation-analyses", json={"analysis": "dimension_mismatch",
            "area_name": "Thanh Đảo", "radius_nm": 20}).json()
        assert analysis["status"] == "complete" and analysis["total"] == 0
        for endpoint in ("missed-carrier-candidates", "false-carrier-candidates", "carrier-investigation-candidates",
                         "carrier-label-review-candidates", "vessel-monitoring-reports"):
            candidates = client.post("/" + endpoint, json={"area_name": "Thanh Đảo", "radius_nm": 20,
                "observed_from": "2026-10-01", "observed_to": "2026-10-01"}).json()
            assert candidates["status"] == "complete"
            assert candidates["total"] == (0 if endpoint.startswith("missed") else 2)
            assert candidates["filters"]["radius_nm"] == 20
            if endpoint == "vessel-monitoring-reports":
                assert candidates["statistics"]["detection_count"] == 2
                assert candidates["statistics_filters"]["radius_nm"] == 20
        query = {"area_name": "Thanh Đảo", "radius_nm": 20,
                 "observed_from": "2026-10-01", "observed_to": "2026-10-01"}
        clusters = client.post("/carrier-hotspots", json=query).json()
        assert clusters["total_detections"] == 2 and clusters["total"] == 1
        members = client.post("/carrier-hotspot-candidates", json={**query,
            "report_id": clusters["report_id"], "cluster_id": clusters["clusters"][0]["cluster_id"]}).json()
        assert members["total"] == 2 and members["filters"]["radius_nm"] == 20
