"""Demo graph plus a small local image server, independent of the production API."""

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from langchain_core.runnables import RunnableConfig

from file_server.media.charts import render_carrier_chart
from file_server.services.carrier_reports import daily_carrier_report
from ship_agent.artifacts.map_artifacts import render_map
from ship_agent.artifacts.map_snapshots import CreateMapInput, MapFilters, read_map, save_map
from ship_agent.data.demo_data import image_path, load_demo_observations, read_snapshot
from ship_agent.runtime.agent import build_agent


def make_graph(config: RunnableConfig):
    return build_agent(data_source="demo")


def create_app() -> FastAPI:
    snapshot = read_snapshot()
    observations = load_demo_observations()
    records = {row["image_id"]: row for row in snapshot["observations"]}
    ships = {row["ship_id"]: row for row in observations}
    app = FastAPI(title="VesselWatch recording demo — saved satellite crops")

    from file_server.api.area_queries import register_area_routes
    from ship_agent.data.demo_data import demo_root, public_base_url
    register_area_routes(app, observations=lambda request: observations,
                         public_url=lambda request: public_base_url(),
                         storage_root=lambda: demo_root() / "area_queries", source="demo")

    @app.get("/health")
    def health():
        return {"status": "ok", "is_demo": True, "snapshot_id": snapshot["snapshot_id"],
                "observation_count": len(records)}

    @app.post("/maps")
    def create_map(request: CreateMapInput):
        if request.expected_snapshot_id != snapshot["snapshot_id"]:
            raise HTTPException(409, "Demo snapshot changed; restart the demo agent and server.")
        filters = MapFilters.model_validate(request.model_dump(exclude={"expected_snapshot_id"}))
        try:
            return save_map(snapshot, filters)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, "Could not freeze the verified demo data; regenerate the snapshot.") from exc

    @app.get("/maps/{map_id}", response_class=HTMLResponse)
    def vessel_map(map_id: str):
        try:
            payload = read_map(map_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Map not found.") from exc
        except ValueError as exc:
            raise HTTPException(409, "Map snapshot was modified; create a new map.") from exc
        return HTMLResponse(render_map(payload), headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/images/{image_id}")
    def image(image_id: str, original: bool = False, preview: bool = False):
        row = records.get(image_id)
        if row is None:
            raise HTTPException(404, "Demo image not found.")
        path = image_path(row)
        if original and not preview:
            return FileResponse(path)
        if preview:
            from file_server.media.image_assets import prepare_preview_image
            variant = prepare_preview_image(path.read_bytes())
            return Response(variant.data, media_type="image/png", headers={
                "Cache-Control": "no-store", "X-Original-Width": str(variant.original_width),
                "X-Original-Height": str(variant.original_height)})
        # Preserve the original crop on disk; enlarge only its chat preview.
        from io import BytesIO
        from PIL import Image
        with Image.open(path) as source:
            scale = min(640 / source.width, 480 / source.height)
            size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
            preview = source.resize(size, Image.Resampling.NEAREST)
            output = BytesIO()
            preview.save(output, format="PNG")
        return Response(output.getvalue(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/ships/{ship_id}")
    def ship(ship_id: str):
        if ship_id not in ships:
            raise HTTPException(404, "Demo observation not found.")
        return ships[ship_id]

    @app.get("/charts/daily-carriers.png")
    def carrier_chart(
        observed_from: date, observed_to: date,
        report_id: str = Query(pattern=r"^[a-f0-9]{64}$"),
        snapshot_id: str = Query(pattern=r"^[a-f0-9]{64}$"),
    ):
        if snapshot_id != snapshot["snapshot_id"]:
            raise HTTPException(409, "Demo snapshot changed; request a new chart.")
        try:
            report = daily_carrier_report(observations, observed_from, observed_to)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if report_id != report["report_id"]:
            raise HTTPException(409, "Report data changed; request a new chart.")
        return Response(render_carrier_chart(report), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/report-preview", response_class=HTMLResponse)
    def report_preview():
        from datetime import date, timedelta
        from ship_agent.artifacts.report_artifacts import render_carrier_artifact
        from ship_agent.tools.registry import create_tools
        last = date.fromisoformat(snapshot["reference_date"])
        report = create_tools(data_source="demo")[2].invoke({
            "observed_from": (last - timedelta(days=6)).isoformat(),
            "observed_to": last.isoformat(),
        })
        return HTMLResponse(render_carrier_artifact(report))

    return app
