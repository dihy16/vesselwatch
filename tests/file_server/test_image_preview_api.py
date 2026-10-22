"""The optional preview query keeps original downloads and revision guards intact."""

from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from file_server.api.observations import register_observations_routes
from file_server.api.references import register_references_routes
from file_server.data.store import ObservationStore
from file_server.media.carrier_references import load_reference_library
from tests.file_server.test_carrier_references import png, reference_folder


def test_registered_source_and_preview_are_separate_and_sources_are_not_written(tmp_path):
    raw = png(size=(48, 26))
    path = tmp_path / "crop.png"
    path.write_bytes(raw)
    app = FastAPI()
    app.state.store = ObservationStore([], {}, {"id": (path.name, "image/png")}, tmp_path, {})
    register_observations_routes(app)
    with TestClient(app) as client:
        assert client.get("/images/id").content == raw
        preview = client.get("/images/id?preview=1")
        assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
        assert preview.headers["x-original-width"] == "48"
        with Image.open(BytesIO(preview.content)) as image:
            assert image.size == (384, 208)
        assert client.get("/images/id").content == raw and path.read_bytes() == raw
        assert client.get("/images/unknown?preview=1").status_code == 404
        path.write_bytes(b"invalid-image")
        assert client.get("/images/id?preview=1").status_code == 422


def test_reference_preview_cannot_bypass_revision_guard(tmp_path):
    library = load_reference_library(reference_folder(tmp_path))
    app = FastAPI()
    app.state.settings = SimpleNamespace(carrier_reference_dir=tmp_path, base_url="http://public")
    app.state.carrier_reference_library = None
    register_references_routes(app)
    image = library.images[0]
    with TestClient(app) as client:
        manifest = client.get("/carrier-references").json()
        assert manifest["revision"] == library.revision
        url = f"/carrier-references/images/{image.reference_id}?revision={library.revision}"
        assert client.get(url).content == image.data
        preview = client.get(url + "&preview=1")
        assert preview.status_code == 200 and preview.headers["x-original-width"] == "32"
        with Image.open(BytesIO(preview.content)) as enlarged:
            assert enlarged.size == (384, 288)
        wrong = f"/carrier-references/images/{image.reference_id}?revision={'0' * 64}&preview=1"
        assert client.get(wrong).status_code == 409
        assert (tmp_path / "known.png").read_bytes() == image.data
