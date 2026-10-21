"""Named query areas and validated user polygons, in GeoJSON lon/lat order."""

from copy import deepcopy
from functools import lru_cache
import gzip
import json
from pathlib import Path
import unicodedata

from file_server.schemas.geometry import _on_edge


AREA_DATA = Path(__file__).resolve().parents[1] / "area_data"
AREA_NAMES = {"bien_dong": "Biển Đông", "vinh_bac_bo": "Vịnh Bắc Bộ"}


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
