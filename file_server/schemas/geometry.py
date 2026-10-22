"""GeoJSON polygon validation and primitive geometry predicates."""

from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

def _on_edge(p, a, b):
    return (abs(_cross(a, b, p)) <= 1e-10
            and min(a[0], b[0]) - 1e-10 <= p[0] <= max(a[0], b[0]) + 1e-10
            and min(a[1], b[1]) - 1e-10 <= p[1] <= max(a[1], b[1]) + 1e-10)

def _intersects(a, b, c, d):
    return (any((_on_edge(p, u, v)) for p, u, v in
                ((a, c, d), (b, c, d), (c, a, b), (d, a, b)))
            or (_cross(a, b, c) * _cross(a, b, d) < 0
                and _cross(c, d, a) * _cross(c, d, b) < 0))

class UserPolygon(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    type: str = "Polygon"
    coordinates: list[list[list[float]]] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def valid_ring(self):
        ring = self.coordinates[0]
        if self.type != "Polygon" or not 4 <= len(ring) <= 201:
            raise ValueError("Vẽ polygon có từ 3 đến 200 đỉnh.")
        if any(len(p) != 2 or not all(isfinite(v) for v in p)
               or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in ring):
            raise ValueError("Tọa độ phải là [kinh độ, vĩ độ] hợp lệ.")
        if ring[0] != ring[-1] or len({tuple(p) for p in ring[:-1]}) != len(ring) - 1:
            raise ValueError("Polygon phải khép kín và không lặp đỉnh.")
        if any(abs(a[0] - b[0]) > 180 for a, b in zip(ring, ring[1:])):
            raise ValueError("Vùng vẽ không được đi qua kinh tuyến 180 độ.")
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))
        if abs(area) < 1e-10:
            raise ValueError("Polygon phải có diện tích lớn hơn 0.")
        segments = list(zip(ring, ring[1:]))
        for i, (a, b) in enumerate(segments):
            for j in range(i + 1, len(segments)):
                if j == i + 1 or (i == 0 and j == len(segments) - 1):
                    continue
                if _intersects(a, b, *segments[j]):
                    raise ValueError("Các cạnh polygon không được tự cắt nhau.")
        return self
