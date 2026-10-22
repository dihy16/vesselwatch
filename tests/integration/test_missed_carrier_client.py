"""Candidate transport rejects incomplete or out-of-scope image-review inputs."""

from copy import deepcopy
import json

import httpx
import pytest

from ship_agent.clients.area_client import request_missed_carrier_candidates
from tests.file_server.test_observation_analysis import row


def response_payload():
    candidate = row("a", length=250, score=.01, label="not_aircraft_carrier", day="2025-01-01")
    candidate.update(ship_url="http://public/ships/a", images=[{"image_id": "image-a",
        "url": "http://public/images/a", "mime_type": "image/png", "caption": "target"}])
    return {"status": "complete", "area_id": "a" * 32, "map_url": "http://public/map",
            "source_snapshot_id": "b" * 64, "total": 1, "limit": 20, "offset": 0,
            "filters": {"classification": "not_aircraft_carrier"}, "ships": [candidate]}


QUERY = {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}


def test_uses_candidate_endpoint_and_validates_registered_observation():
    def respond(request):
        assert request.url.path == "/missed-carrier-candidates"
        assert json.loads(request.content) == QUERY
        return httpx.Response(200, json=response_payload())
    result = request_missed_carrier_candidates(QUERY, transport=httpx.MockTransport(respond))
    assert result["total"] == 1 and result["ships"][0]["length_m"] == 250


@pytest.mark.parametrize("field,value", [("confidence", .01001), ("length_m", 249.99),
    ("confidence", None), ("classification", "aircraft_carrier"), ("observed_date", "2026-01-01"),
    ("observed_at", "2025-01-02T00:00:00Z"), ("observed_at", "2025-01-01T00:00:00+07:00")])
def test_wrong_candidate_never_reaches_image_review(field, value):
    data = response_payload()
    data["ships"][0][field] = value
    with pytest.raises(ValueError):
        request_missed_carrier_candidates(QUERY, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)))


@pytest.mark.parametrize("kind", ["missing-page", "duplicate-id", "missing-snapshot", "wrong-offset"])
def test_partial_or_mixed_candidate_page_rejected(kind):
    data = response_payload()
    if kind == "missing-page":
        data["total"] = 2
    elif kind == "duplicate-id":
        data["total"] = 2
        data["ships"].append(deepcopy(data["ships"][0]))
    elif kind == "missing-snapshot":
        data.pop("source_snapshot_id")
    else:
        data["offset"] = 2
    with pytest.raises(ValueError):
        request_missed_carrier_candidates(QUERY, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)))
