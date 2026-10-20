"""Local FastAPI data server; independent of LangGraph and the mock agent."""

from contextlib import asynccontextmanager
from datetime import date
import logging
import json
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .carrier_reports import daily_carrier_report, render_carrier_chart
from .config import DataSettings
from .loader import Observation, load_store, registered_image


class ObservationPage(BaseModel):
    is_mock: bool = False
    timezone: str = "UTC"
    total: int
    limit: int
    offset: int
    observations: list[Observation]


def create_app(settings: DataSettings | None = None) -> FastAPI:
    """Load a shared snapshot at startup; inject settings for local tests."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings or DataSettings.from_config()
        app.state.store = load_store(app.state.settings)
        app.state.carrier_reference_library = None
        logging.getLogger(__name__).info("Loaded data snapshot: %s", app.state.store.summary)
        yield
        del app.state.store

    app = FastAPI(title="Vesselwatch data API", lifespan=lifespan)

    from . import config
    from .carrier_references import load_reference_library

    def reference_library(request, *, refresh=False):
        library = getattr(request.app.state, "carrier_reference_library", None)
        if library is None or refresh:
            directory = request.app.state.settings.carrier_reference_dir or config.CARRIER_REFERENCE_DIR
            try:
                library = load_reference_library(directory)
            except (OSError, ValueError) as exc:
                raise HTTPException(503, "Chưa nạp được bộ mẫu: kiểm tra CARRIER_REFERENCE_DIR, description.md và ảnh hợp lệ (≤10 MB/16 MP mỗi ảnh).") from exc
            request.app.state.carrier_reference_library = library
        return library

    @app.get("/carrier-references")
    def carrier_references(request: Request):
        library = reference_library(request, refresh=True)
        return Response(content=json.dumps(library.manifest(request.app.state.settings.base_url),
                                           ensure_ascii=False).encode("utf-8"),
                        media_type="application/json", headers={"Cache-Control": "no-store"})

    @app.get("/carrier-references/images/{reference_id}")
    def carrier_reference_image(reference_id: str, request: Request,
                                revision: str = Query(pattern=r"^[a-f0-9]{64}$")):
        library = reference_library(request)
        if revision != library.revision:
            raise HTTPException(409, "Bộ mẫu đã thay đổi; tải lại danh sách ảnh mẫu.")
        image = next((image for image in library.images if image.reference_id == reference_id), None)
        if image is None:
            raise HTTPException(404, "Không tìm thấy ảnh mẫu.")
        return Response(image.data, media_type="image/png", headers={"Cache-Control": "no-store"})

    from .area_queries import register_area_routes
    register_area_routes(
        app, observations=lambda request: [o.model_dump() for o in request.app.state.store.observations],
        public_url=lambda request: request.app.state.settings.base_url,
        storage_root=lambda: config.AREA_QUERY_DIR, source="file_server",
    )

    @app.get("/health")
    def health(request: Request):
        return {"status": "ok", "is_mock": False, "timezone": "UTC",
                **request.app.state.store.summary}

    @app.get("/observations", response_model=ObservationPage)
    def observations(
        request: Request, observed_from: date | None = None, observed_to: date | None = None,
        limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    ):
        if observed_from and observed_to and observed_from > observed_to:
            raise HTTPException(422, "observed_from must be before or equal to observed_to.")
        first = observed_from.isoformat() if observed_from else None
        last = observed_to.isoformat() if observed_to else None
        matches = [o for o in request.app.state.store.observations
                   if (first is None or o.observed_date >= first)
                   and (last is None or o.observed_date <= last)]
        return ObservationPage(total=len(matches), limit=limit, offset=offset,
                               observations=matches[offset:offset + limit])

    @app.get("/ships/{ship_id:path}", response_model=Observation)
    def ship(ship_id: str, request: Request, observation_id: str | None = None):
        store = request.app.state.store
        observation = store.ships.get(ship_id)
        if observation_id is not None:
            observation = next((o for o in store.observations
                                if o.ship_id == ship_id and o.observation_id == observation_id), None)
        if observation is None:
            raise HTTPException(404, "Ship not found.")
        return observation

    @app.get("/images/{image_id}", response_class=FileResponse)
    def image(image_id: str, request: Request):
        store = request.app.state.store
        registered = store.images.get(image_id)
        if registered is None:
            raise HTTPException(404, "Image not found.")
        name, mime = registered
        path = registered_image(store.image_root, name)
        if path is None:
            raise HTTPException(404, "Image file unavailable.")
        return FileResponse(path, media_type=mime)

    def build_report(request: Request, first: date, last: date):
        try:
            return daily_carrier_report(
                (o.model_dump() for o in request.app.state.store.observations), first, last,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/reports/daily-carriers")
    def carrier_report(request: Request, observed_from: date, observed_to: date):
        report = build_report(request, observed_from, observed_to)
        base = request.app.state.settings.base_url.rstrip("/")
        query = urlencode({"observed_from": report["observed_from"],
                           "observed_to": report["observed_to"],
                           "report_id": report["report_id"]})
        return {**report, "is_mock": False,
                "chart_url": f"{base}/charts/daily-carriers.png?{query}",
                "coverage": request.app.state.store.summary}

    @app.get("/charts/daily-carriers.png", response_class=Response)
    def carrier_chart(
        request: Request, observed_from: date, observed_to: date,
        report_id: str = Query(pattern=r"^[a-f0-9]{64}$"),
    ):
        report = build_report(request, observed_from, observed_to)
        if report["report_id"] != report_id:
            raise HTTPException(409, "Report data changed; request a new daily carrier report.")
        return Response(render_carrier_chart(report), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})

    return app
