"""Area query, map and confirmation routes shared by real and demo apps."""

from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from file_server.api.area_context import AreaContext
from file_server.api.investigations import register_investigation_routes
from file_server.api.langgraph import ask_area_agent
from file_server.schemas.area_confirmation import AreaConfirmation
from file_server.schemas.area_models import AreaQueryInput
from file_server.services.spatial import AREA_NAMES, predefined_geometry, query_observations
from file_server.storage.area_records import _write


def register_area_routes(app, *, observations, public_url, storage_root, source):
    router = APIRouter()
    context = AreaContext(observations=observations, public_url=public_url, storage_root=storage_root, source=source)
    router.post("/area-queries")(context.query_area)
    register_investigation_routes(router, context)

    @router.get("/query-areas/{key}")
    def area_boundary(key: str):
        if key not in AREA_NAMES:
            raise HTTPException(404, "Khu vực này cần người dùng tự vẽ.")
        return {"type": "Feature", "properties": {"name": AREA_NAMES[key]},
                "geometry": predefined_geometry(key).geometry}

    @router.get("/area-queries/{area_id}", response_class=HTMLResponse)
    def area_map(area_id: str, request: Request):
        from ship_agent.artifacts.map_artifacts import render_map

        rows, _, record = context.checked_record(request, area_id)
        query = AreaQueryInput.model_validate(record["query"])
        matches = query_observations(rows, query, context.geometry_for(record))
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

    @router.post("/area-queries/{area_id}/confirm")
    def confirm_area(area_id: str, body: AreaConfirmation, request: Request):
        rows, root, record = context.checked_record(request, area_id)
        record.update(status="complete", area_name="Vùng tùy ý", named_area=None,
                      polygon=body.polygon.model_dump())
        new_id = _write(root, record)
        return context.result_for(request, new_id, record, rows)

    @router.post("/area-queries/{area_id}/answer")
    async def answer_area(area_id: str, request: Request):
        _, _, record = context.checked_record(request, area_id)
        if record["status"] != "complete":
            raise HTTPException(409, "Người dùng chưa xác nhận vùng.")
        query = {**record["query"], "area_id": area_id, "area_name": None}
        return {"area_id": area_id, "answer": await ask_area_agent(query, source=context.source)}

    app.include_router(router)
