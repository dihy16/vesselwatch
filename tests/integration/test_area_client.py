"""Spatial tool transport checks with no live data service."""

import httpx
import pytest

from ship_agent.area_client import request_area_query


def test_uses_internal_server_but_preserves_public_selection_url(monkeypatch):
    monkeypatch.setenv("VESSELWATCH_DEMO_API_URL", "http://internal:8002")

    def respond(request):
        assert str(request.url) == "http://internal:8002/area-queries"
        return httpx.Response(200, json={"status": "needs_drawing", "selection_id": "a" * 32,
                                        "map_url": "http://viewer:8002/area-queries/" + "a" * 32})

    result = request_area_query({"area_name": "X"}, data_source="demo", transport=httpx.MockTransport(respond))
    assert result["map_url"].startswith("http://viewer:8002")


@pytest.mark.parametrize("result", [
    {}, {"status": "complete", "area_id": "invalid"},
    {"status": "needs_drawing", "selection_id": "a" * 32, "map_url": "javascript:bad"},
    {"status": "complete", "area_id": "a" * 32, "map_url": "http://viewer/map", "total": -1, "ships": []},
])
def test_bad_response_is_an_error_not_empty_results(result):
    with pytest.raises(ValueError):
        request_area_query({}, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result)))
