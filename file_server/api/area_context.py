"""Request-scoped area resolution shared by real and demo routers."""

from hashlib import sha256
import json
from pathlib import Path

from fastapi import HTTPException, Request

from file_server.schemas.area_models import AreaQueryInput, AreaRequest
from file_server.schemas.geometry import UserPolygon
from file_server.services.spatial import (
    AREA_NAMES,
    AREA_CENTERS,
    AreaGeometry,
    named_area,
    named_center,
    square_polygon,
    predefined_geometry,
    query_observations,
)
from file_server.storage.area_records import _write, _read, AreaNotFound


class AreaContext:
    def __init__(self, *, observations, public_url, storage_root, source):
        self.observations = observations
        self.public_url = public_url
        self.storage_root = storage_root
        self.source = source

    def context(self, request):
        rows = self.observations(request)
        fingerprint = sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        return rows, Path(self.storage_root()), fingerprint

    def checked_record(self, request, area_id):
        rows, root, fingerprint = self.context(request)
        try:
            record = _read(root, area_id)
        except AreaNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        if record["snapshot_id"] != fingerprint:
            raise HTTPException(409, "Dữ liệu nguồn đã thay đổi; hãy tạo lại truy vấn vùng.")
        return rows, root, record

    def geometry_for(self, record):
        if record.get("named_area"):
            return predefined_geometry(record["named_area"])
        if record.get("polygon"):
            return AreaGeometry(UserPolygon.model_validate(record["polygon"]).model_dump())
        return None

    def result_for(self, request, area_id, record, rows):
        query = AreaQueryInput.model_validate(record["query"])
        matches = query_observations(rows, query, self.geometry_for(record))
        return {"status": "complete", "area_id": area_id, "area_name": record["area_name"],
                "count_unit": "detections", "timezone": "UTC", "is_demo": self.source == "demo",
                "filters": query.model_dump(), "total": len(matches),
                "square_area": record.get("square_area"),
                "possible_aircraft_carrier_count": sum(r["classification"] == "aircraft_carrier" for r in matches),
                "limit": query.limit, "offset": query.offset,
                "ships": matches[query.offset:query.offset + query.limit],
                "map_url": self.public_url(request).rstrip("/") + f"/area-queries/{area_id}"}

    def query_area(self, body: AreaRequest, request: Request):
        rows, root, fingerprint = self.context(request)
        query = AreaQueryInput.model_validate(body.model_dump(exclude={"polygon"}))
        key = named_area(query.area_name)
        area_name = AREA_NAMES.get(key, "Vùng tùy ý" if body.polygon else query.area_name)
        polygon = body.polygon.model_dump() if body.polygon else None
        square_area = None
        if query.radius_nm is not None:
            center = AREA_CENTERS.get(named_center(query.area_name)) or {
                "name": "Tọa độ tùy chọn", "latitude": query.center_latitude,
                "longitude": query.center_longitude}
            polygon = square_polygon(center["latitude"], center["longitude"], query.radius_nm)
            square_area = {**center, "radius_nm": query.radius_nm, "side_nm": 2 * query.radius_nm}
            area_name = f"{center['name']} ±{query.radius_nm:g} hải lý (ô vuông)"
        if query.area_id:
            _, _, previous = self.checked_record(request, query.area_id)
            if previous["status"] != "complete":
                raise HTTPException(409, "Người dùng chưa vẽ và xác nhận vùng.")
            key, polygon, area_name = previous.get("named_area"), previous.get("polygon"), previous["area_name"]
            square_area = previous.get("square_area")
        waiting = bool(query.area_name and not key and not polygon)
        record = {"status": "needs_drawing" if waiting else "complete", "query": query.model_dump(),
                  "area_name": area_name, "named_area": key, "polygon": polygon,
                  "square_area": square_area,
                  "snapshot_id": fingerprint}
        area_id = _write(root, record)
        if waiting:
            return {"status": "needs_drawing", "selection_id": area_id,
                    "map_url": self.public_url(request).rstrip("/") + f"/area-queries/{area_id}",
                    "area_name": area_name, "filters": query.model_dump(),
                    "message": "Vẽ rectangle/polygon trên bản đồ rồi bấm Xác nhận và hỏi agent."}
        return self.result_for(request, area_id, record, rows)
