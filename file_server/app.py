"""Local FastAPI data server; independent of LangGraph and the mock agent."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from file_server.api.observations import register_observations_routes
from file_server.api.references import register_references_routes
from file_server.api.reports import register_reports_routes
from file_server.config import DataSettings
from file_server.data.loader import load_store


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

    from file_server import config
    from file_server.api.area_queries import register_area_routes
    register_area_routes(
        app, observations=lambda request: [o.model_dump() for o in request.app.state.store.observations],
        public_url=lambda request: request.app.state.settings.base_url,
        storage_root=lambda: config.AREA_QUERY_DIR, source="file_server",
    )

    register_observations_routes(app)
    register_references_routes(app)
    register_reports_routes(app)
    return app
