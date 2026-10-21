"""Fetch all reference pixels only through the backend and verify snapshot integrity."""

import httpx
import pytest

from file_server.media.carrier_references import load_reference_library
from ship_agent.clients.carrier_reference_client import load_carrier_references
from tests.file_server.test_carrier_references import png, reference_folder


def test_downloads_every_reference_without_following_public_urls(tmp_path):
    reference_folder(tmp_path)
    (tmp_path / "second.png").write_bytes(png("red"))
    library = load_reference_library(tmp_path)
    requests = []
    def respond(req):
        requests.append(req)
        assert req.url.host != "arbitrary-public.example"
        if req.url.path == "/carrier-references":
            return httpx.Response(200, json=library.manifest("http://arbitrary-public.example"))
        assert req.url.params["revision"] == library.revision
        identity = req.url.path.rsplit("/", 1)[1]
        image = next(image for image in library.images if image.reference_id == identity)
        return httpx.Response(200, content=image.data)
    fetched = load_carrier_references(transport=httpx.MockTransport(respond))
    assert len(requests) == 3 and fetched == library


@pytest.mark.parametrize("failure", ["http", "corrupt-bytes", "missing-description", "duplicates", "wrong-revision"])
def test_library_errors_never_silently_remove_an_image(tmp_path, failure):
    library = load_reference_library(reference_folder(tmp_path))
    manifest = library.manifest("http://public")
    if failure == "missing-description":
        manifest["description"] = ""
    elif failure == "duplicates":
        manifest["images"] *= 2
    elif failure == "wrong-revision":
        manifest["revision"] = "0" * 64
    def respond(req):
        if req.url.path == "/carrier-references":
            return httpx.Response(200, json=manifest)
        if failure == "http":
            return httpx.Response(404)
        return httpx.Response(200, content=b"corrupt" if failure == "corrupt-bytes" else library.images[0].data)
    with pytest.raises((ValueError, httpx.HTTPError)):
        load_carrier_references(transport=httpx.MockTransport(respond))
