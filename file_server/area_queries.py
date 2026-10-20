"""Shared spatial query API and map confirmation for real and demo snapshots."""

from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from .spatial import (AREA_NAMES, AreaGeometry, UserPolygon, named_area,
                      predefined_geometry, query_observations)
from .area_models import AreaQueryInput, AreaRequest


class AreaConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    polygon: UserPolygon


def _write(root, record):
    root.mkdir(parents=True, exist_ok=True)
    area_id = uuid4().hex
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as output:
            temporary = Path(output.name)
            json.dump(record, output, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, root / f"{area_id}.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return area_id


def _read(root, area_id):
    if not re.fullmatch(r"[a-f0-9]{32}", area_id):
        raise HTTPException(404, "Không tìm thấy vùng truy vấn.")
    try:
        return json.loads((root / f"{area_id}.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(404, "Không tìm thấy vùng truy vấn.") from exc


async def ask_area_agent(query: dict, *, source: str) -> str:
    """Call the configured LangGraph server; credentials remain on that server."""
    from ship_agent import config

    url = config.DEMO_LANGGRAPH_URL if source == "demo" else config.LANGGRAPH_URL
    message = ("Truy vấn các lượt phát hiện trong vùng đã được người dùng xác nhận. "
               "Dùng query_ships_in_area với đúng tham số sau, trả tổng số lượt phát hiện, "
               "số lượt nghi là tàu sân bay và danh sách kèm vị trí; nói rõ nếu có phân trang.\n"
               + json.dumps(query, ensure_ascii=False))
    try:
        async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
            response = await client.post(url.rstrip("/") + "/runs/wait", json={
                "assistant_id": "agent", "input": {"messages": [{"role": "user", "content": message}]},
                "config": {"recursion_limit": 20},
            })
            response.raise_for_status()
            state = response.json()
        if not isinstance(state, dict) or not isinstance(state.get("messages"), list):
            raise ValueError("Phản hồi agent không hợp lệ.")
        for item in reversed(state.get("messages", [])):
            if item.get("type") == "ai" and not item.get("tool_calls"):
                content = item.get("content")
                if isinstance(content, list):
                    content = "\n".join(block["text"] for block in content
                                        if isinstance(block, dict) and isinstance(block.get("text"), str))
                if isinstance(content, str) and content.strip():
                    return content
        raise ValueError("Agent chưa trả câu trả lời.")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Chưa nhận được câu trả lời từ agent. Kiểm tra URL và server LangGraph.") from exc


def register_area_routes(app, *, observations, public_url, storage_root, source):
    """Providers receive Request so production data still loads during lifespan."""
    def context(request):
        rows = observations(request)
        fingerprint = sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        return rows, Path(storage_root()), fingerprint

    def checked_record(request, area_id):
        rows, root, fingerprint = context(request)
        record = _read(root, area_id)
        if record["snapshot_id"] != fingerprint:
            raise HTTPException(409, "Dữ liệu nguồn đã thay đổi; hãy tạo lại truy vấn vùng.")
        return rows, root, record

    def geometry_for(record):
        if record.get("named_area"):
            return predefined_geometry(record["named_area"])
        if record.get("polygon"):
            return AreaGeometry(UserPolygon.model_validate(record["polygon"]).model_dump())
        return None

    def result_for(request, area_id, record, rows):
        query = AreaQueryInput.model_validate(record["query"])
        matches = query_observations(rows, query, geometry_for(record))
        return {"status": "complete", "area_id": area_id, "area_name": record["area_name"],
                "count_unit": "detections", "timezone": "UTC", "is_demo": source == "demo",
                "filters": query.model_dump(), "total": len(matches),
                "possible_aircraft_carrier_count": sum(r["classification"] == "aircraft_carrier" for r in matches),
                "limit": query.limit, "offset": query.offset,
                "ships": matches[query.offset:query.offset + query.limit],
                "map_url": public_url(request).rstrip("/") + f"/area-queries/{area_id}"}

    @app.get("/query-areas/{key}")
    def area_boundary(key: str):
        if key not in AREA_NAMES:
            raise HTTPException(404, "Khu vực này cần người dùng tự vẽ.")
        return {"type": "Feature", "properties": {"name": AREA_NAMES[key]},
                "geometry": predefined_geometry(key).geometry}

    @app.post("/area-queries")
    def query_area(body: AreaRequest, request: Request):
        rows, root, fingerprint = context(request)
        query = AreaQueryInput.model_validate(body.model_dump(exclude={"polygon"}))
        key = named_area(query.area_name)
        area_name = AREA_NAMES.get(key, "Vùng tùy ý" if body.polygon else query.area_name)
        polygon = body.polygon.model_dump() if body.polygon else None
        if query.area_id:
            _, _, previous = checked_record(request, query.area_id)
            if previous["status"] != "complete":
                raise HTTPException(409, "Người dùng chưa vẽ và xác nhận vùng.")
            key, polygon, area_name = previous.get("named_area"), previous.get("polygon"), previous["area_name"]
        waiting = bool(query.area_name and not key and not polygon)
        record = {"status": "needs_drawing" if waiting else "complete", "query": query.model_dump(),
                  "area_name": area_name, "named_area": key, "polygon": polygon,
                  "snapshot_id": fingerprint}
        area_id = _write(root, record)
        if waiting:
            return {"status": "needs_drawing", "selection_id": area_id,
                    "map_url": public_url(request).rstrip("/") + f"/area-queries/{area_id}",
                    "area_name": area_name, "filters": query.model_dump(),
                    "message": "Vẽ rectangle/polygon trên bản đồ rồi bấm Xác nhận và hỏi agent."}
        return result_for(request, area_id, record, rows)

    @app.get("/area-queries/{area_id}", response_class=HTMLResponse)
    def area_map(area_id: str, request: Request):
        from ship_agent.map_artifacts import render_map

        rows, _, record = checked_record(request, area_id)
        query = AreaQueryInput.model_validate(record["query"])
        matches = query_observations(rows, query, geometry_for(record))
        dates = [r["observed_date"] for r in rows]
        filters = query.model_dump()
        filters["observed_from"] = query.observed_from or min(dates, default=date.today().isoformat())
        filters["observed_to"] = query.observed_to or max(dates, default=date.today().isoformat())
        vessels = [{"id": r["observation_id"], "name": r["ship_id"], **r["position"],
                    "captured_at": r["observed_at"],
                    "position_status": "unavailable" if r["position"]["latitude"] is None else "available",
                    "image_path": r["images"][0]["url"] if r["images"] else "",
                    "prediction": {"carrier_score": r["confidence"]},
                    "metadata": {"source_id": r["ship_id"], "length_m": r["length_m"],
                                 "width_m": r["width_m"], "classification": r["classification"]}}
                   for r in matches]
        controls = {"query": query.model_dump(), "selection_id": area_id,
                    "prepare_url": "/area-queries", "confirm_url": f"/area-queries/{area_id}/confirm",
                    "name": record["area_name"], "named_area": record.get("named_area"),
                    "polygon": record.get("polygon")}
        return HTMLResponse(render_map({"filters": filters, "vessels": vessels,
                                        "area_query": controls}), headers={"Cache-Control": "no-store"})

    @app.post("/area-queries/{area_id}/confirm")
    def confirm_area(area_id: str, body: AreaConfirmation, request: Request):
        rows, root, record = checked_record(request, area_id)
        record.update(status="complete", area_name="Vùng tùy ý", named_area=None,
                      polygon=body.polygon.model_dump())
        new_id = _write(root, record)
        return result_for(request, new_id, record, rows)

    @app.post("/area-queries/{area_id}/answer")
    async def answer_area(area_id: str, request: Request):
        _, _, record = checked_record(request, area_id)
        if record["status"] != "complete":
            raise HTTPException(409, "Người dùng chưa xác nhận vùng.")
        query = {**record["query"], "area_id": area_id, "area_name": None}
        return {"area_id": area_id, "answer": await ask_area_agent(query, source=source)}
