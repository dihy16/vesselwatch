"""Reference endpoints expose immutable registered pixels and explicit missing-library errors."""

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from file_server.app import create_app
from file_server.config import DataSettings
from file_server.data.store import ObservationStore
from tests.file_server.test_carrier_references import reference_folder, png


def test_library_manifest_images_refresh_conflict_and_missing_data(tmp_path, monkeypatch):
    monkeypatch.setattr("file_server.app.load_store", lambda _: ObservationStore([], {}, {}, tmp_path, {}))
    settings = DataSettings(Path("unused"), tmp_path, Path("unused"), carrier_reference_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/carrier-references").status_code == 503
        reference_folder(tmp_path)
        manifest = client.get("/carrier-references").json()
        assert len(manifest["images"]) == 1
        old_url = manifest["images"][0]["url"]
        response = client.get(old_url)
        assert response.status_code == 200 and response.headers["content-type"].startswith("image/png")
        assert client.get("/carrier-references/images/unknown", params={"revision": manifest["revision"]}).status_code == 404
        (tmp_path / "known.png").write_bytes(png("red"))
        refreshed = client.get("/carrier-references").json()
        assert refreshed["revision"] != manifest["revision"]
        assert client.get(old_url).status_code == 409
        assert client.get(refreshed["images"][0]["url"]).status_code == 200
