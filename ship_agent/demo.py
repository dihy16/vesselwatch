"""Demo graph plus a small local image server, independent of the production API."""

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from langchain_core.runnables import RunnableConfig

from ship_agent.agent import build_agent
from ship_agent.demo_data import image_path, load_demo_observations, read_snapshot


def make_graph(config: RunnableConfig):
    return build_agent(data_source="demo")


def create_app() -> FastAPI:
    snapshot = read_snapshot()
    observations = load_demo_observations()
    records = {row["image_id"]: row for row in snapshot["observations"]}
    ships = {row["ship_id"]: row for row in observations}
    app = FastAPI(title="VesselWatch recording demo — saved satellite crops")

    @app.get("/health")
    def health():
        return {"status": "ok", "is_demo": True, "snapshot_id": snapshot["snapshot_id"],
                "observation_count": len(records)}

    @app.get("/images/{image_id}")
    def image(image_id: str, original: bool = False):
        row = records.get(image_id)
        if row is None:
            raise HTTPException(404, "Demo image not found.")
        path = image_path(row)
        if original:
            return FileResponse(path)
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

    @app.get("/report-preview", response_class=HTMLResponse)
    def report_preview():
        from datetime import date, timedelta
        from ship_agent.report_artifacts import render_carrier_artifact
        from ship_agent.tools import create_tools
        last = date.fromisoformat(snapshot["reference_date"])
        report = create_tools(data_source="demo")[2].invoke({
            "observed_from": (last - timedelta(days=6)).isoformat(),
            "observed_to": last.isoformat(),
        })
        return HTMLResponse(render_carrier_artifact(report))

    return app
