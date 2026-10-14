"""Local FastAPI data server; independent of LangGraph and the mock agent."""

from contextlib import asynccontextmanager
from datetime import date
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
        app.state.store = load_store(settings or DataSettings.from_config())
        logging.getLogger(__name__).info("Loaded data snapshot: %s", app.state.store.summary)
        yield
        del app.state.store

    app = FastAPI(title="Vesselwatch data API", lifespan=lifespan)

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

    @app.get("/ships/{ship_id}", response_model=Observation)
    def ship(ship_id: str, request: Request):
        observation = request.app.state.store.ships.get(ship_id)
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

    return app
