"""Observations HTTP endpoints."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from file_server.data.store import registered_image
from file_server.media.image_assets import MAX_IMAGE_BYTES, prepare_preview_image
from file_server.schemas.observations import Observation
from file_server.schemas.observations import ObservationPage


def register_observations_routes(app):
    router = APIRouter()

    @router.get("/health")
    def health(request: Request):
        return {"status": "ok", "is_mock": False, "timezone": "UTC",
                **request.app.state.store.summary}

    @router.get("/observations", response_model=ObservationPage)
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

    @router.get("/ships/{ship_id:path}", response_model=Observation)
    def ship(ship_id: str, request: Request, observation_id: str | None = None):
        store = request.app.state.store
        observation = store.ships.get(ship_id)
        if observation_id is not None:
            observation = next((o for o in store.observations
                                if o.ship_id == ship_id and o.observation_id == observation_id), None)
        if observation is None:
            raise HTTPException(404, "Ship not found.")
        return observation

    @router.get("/images/{image_id}", response_class=FileResponse)
    def image(image_id: str, request: Request, preview: bool = False):
        store = request.app.state.store
        registered = store.images.get(image_id)
        if registered is None:
            raise HTTPException(404, "Image not found.")
        name, mime = registered
        path = registered_image(store.image_root, name)
        if path is None:
            raise HTTPException(404, "Image file unavailable.")
        if preview:
            try:
                with path.open("rb") as source:
                    variant = prepare_preview_image(source.read(MAX_IMAGE_BYTES + 1))
            except (OSError, ValueError) as exc:
                raise HTTPException(422, "Không tạo được preview ảnh đăng ký.") from exc
            return Response(variant.data, media_type="image/png", headers={
                "Cache-Control": "no-store", "X-Original-Width": str(variant.original_width),
                "X-Original-Height": str(variant.original_height)})
        return FileResponse(path, media_type=mime)

    app.include_router(router)
