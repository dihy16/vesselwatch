"""Named query areas and validated user polygons, in GeoJSON lon/lat order."""

from copy import deepcopy
from functools import lru_cache
import gzip
import json
from math import cos, degrees, isfinite, radians
from pathlib import Path
import unicodedata

from file_server.schemas.geometry import UserPolygon, _on_edge


AREA_DATA = Path(__file__).resolve().parents[1] / "area_data"
AREA_NAMES = {"bien_dong": "Biển Đông", "vinh_bac_bo": "Vịnh Bắc Bộ"}

# Reference points, not administrative boundaries. Sources and site distinctions
# are documented in area_data/README.md; keep aliases explicit rather than fuzzy.
AREA_CENTERS = {
    "thanh_dao": {"name": "Căn cứ Thanh Đảo (Yuchi)", "latitude": 35.73525, "longitude": 119.99199},
    "du_lam": {"name": "Căn cứ Du Lâm", "latitude": 18.221, "longitude": 109.537},
    "long_pha": {"name": "Căn cứ Long Pha (Du Lâm Đông)", "latitude": 18.21171, "longitude": 109.685},
}


def named_center(value: str | None) -> str | None:
    text = unicodedata.normalize("NFD", value or "").lower().replace("đ", "d")
    text = " ".join("".join(c for c in text if not unicodedata.combining(c))
                    .replace("_", " ").split())
    for prefix in ("khu vuc can cu hai quan ", "khu vuc can cu ", "can cu hai quan ",
                   "khu vuc ", "can cu "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return {"thanh dao": "thanh_dao", "qingdao": "thanh_dao", "yuchi": "thanh_dao",
            "qingdao naval base": "thanh_dao", "du lam": "du_lam", "yulin": "du_lam",
            "yulin naval base": "du_lam", "long pha": "long_pha", "longpo": "long_pha",
            "du lam dong": "long_pha", "east yulin": "long_pha"}.get(text)


def square_polygon(latitude: float, longitude: float, radius_nm: float):
    """N/S/E/W bounds at radius_nm from center in a local spherical projection.

    One nautical mile is exactly 1852 m. Distances use the center latitude, so
    sides are approximately 2*radius_nm on Earth, with longitude correction.
    """
    if (not all(isfinite(v) for v in (latitude, longitude, radius_nm))
            or not -90 < latitude < 90 or not -180 <= longitude <= 180 or radius_nm <= 0):
        raise ValueError("Tâm và khoảng cách hải lý phải hợp lệ, khoảng cách lớn hơn 0.")
    delta_lat = degrees(radius_nm * 1852 / 6371008.8)
    delta_lon = delta_lat / cos(radians(latitude))
    west, east = longitude - delta_lon, longitude + delta_lon
    south, north = latitude - delta_lat, latitude + delta_lat
    if south <= -90 or north >= 90 or west < -180 or east > 180 or east - west > 180:
        raise ValueError("Ô truy vấn không được vượt qua cực hoặc kinh tuyến 180 độ; hãy giảm khoảng cách.")
    return UserPolygon(coordinates=[[[west, south], [east, south], [east, north],
                                     [west, north], [west, south]]]).model_dump()


def named_area(value: str | None) -> str | None:
    """Resolve only explicit Vietnamese names; never approximate another place."""
    text = unicodedata.normalize("NFD", value or "").lower().replace("đ", "d")
    text = " ".join("".join(c for c in text if not unicodedata.combining(c))
                    .replace("_", " ").split())
    return {"bien dong": "bien_dong", "toan bo bien dong": "bien_dong",
            "vinh bac bo": "vinh_bac_bo"}.get(text)


def _bounds(ring):
    return (min(p[0] for p in ring), min(p[1] for p in ring),
            max(p[0] for p in ring), max(p[1] for p in ring))


def _prepare_ring(ring):
    bounds = _bounds(ring)
    height = bounds[3] - bounds[1]
    buckets = [[] for _ in range(256)]
    for a, b in zip(ring, ring[1:]):
        lo = int((min(a[1], b[1]) - bounds[1]) / height * 255) if height else 0
        hi = int((max(a[1], b[1]) - bounds[1]) / height * 255) if height else 0
        for index in range(max(0, lo), min(255, hi) + 1):
            buckets[index].append((a, b))
    return bounds, buckets


def _ring_location(point, bounds, buckets):
    """Return -1 outside, 0 on an edge, 1 inside."""
    x, y = point
    if not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
        return -1
    inside = False
    height = bounds[3] - bounds[1]
    index = min(255, max(0, int((y - bounds[1]) / height * 255))) if height else 0
    for a, b in buckets[index]:
        if _on_edge(point, a, b):
            return 0
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return 1 if inside else -1


class AreaGeometry:
    """Prepare ring bounds once; support source MultiPolygons and their holes."""

    def __init__(self, geometry):
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        self.polygons = [[_prepare_ring(ring) for ring in polygon] for polygon in polygons]
        self.geometry = geometry

    def covers(self, longitude, latitude):
        point = (longitude, latitude)
        for polygon in self.polygons:
            outer = _ring_location(point, *polygon[0])
            if outer == -1:
                continue
            if outer == 0:
                return True
            holes = [_ring_location(point, *ring) for ring in polygon[1:]]
            if 0 in holes or 1 not in holes:
                return True
        return False


@lru_cache(maxsize=2)
def predefined_geometry(key: str) -> AreaGeometry:
    if key not in AREA_NAMES:
        raise ValueError("Khu vực này cần người dùng tự vẽ.")
    with gzip.open(AREA_DATA / f"{key}.geojson.gz", "rt", encoding="utf-8") as source:
        return AreaGeometry(json.load(source))


def query_observations(observations, query, geometry=None):
    """Filter the complete snapshot before pagination; deduplicate observations."""
    found = {}
    for row in observations:
        if ((query.observed_from and row["observed_date"] < query.observed_from)
                or (query.observed_to and row["observed_date"] > query.observed_to)
                or (query.ship_id and row["ship_id"] != query.ship_id)
                or (query.classification and row["classification"] != query.classification)):
            continue
        if query.length_gt_m is not None and (row["length_m"] is None or row["length_m"] <= query.length_gt_m):
            continue
        if query.carrier_score_gt is not None and (row["confidence"] is None
                                                   or row["confidence"] <= query.carrier_score_gt):
            continue
        if any((getattr(query, "min_" + field) is not None and (row[field] is None or row[field] < getattr(query, "min_" + field)))
               or (getattr(query, "max_" + field) is not None and (row[field] is None or row[field] > getattr(query, "max_" + field)))
               for field in ("length_m", "width_m")):
            continue
        position = row["position"]
        if geometry and (position["longitude"] is None or position["latitude"] is None
                         or not geometry.covers(position["longitude"], position["latitude"])):
            continue
        identity = row["observation_id"]
        if identity not in found or row["observed_at"] > found[identity]["observed_at"]:
            found[identity] = row
    return deepcopy(sorted(found.values(), key=lambda row: (row["observed_at"], row["observation_id"])))
