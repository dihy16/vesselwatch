"""Review transport preserves stored positive labels and complete, UTC-scoped pages."""

from copy import deepcopy
import json

import httpx
import pytest

from ship_agent.clients.area_client import request_false_carrier_candidates
from tests.integration.test_missed_carrier_client import response_payload, QUERY


def positive_payload():
    payload = response_payload()
    payload["filters"]["classification"] = "aircraft_carrier"
    payload["ships"][0].update(classification="aircraft_carrier", confidence=.5, length_m=None, width_m=None)
    return payload


@pytest.mark.parametrize("score,length", [(.5, 100), (.99, 300), (None, None), (.001, 200)])
def test_source_label_is_the_only_classification_gate(score, length):
    payload = positive_payload()
    payload["ships"][0].update(confidence=score, length_m=length)
    def respond(request):
        assert request.url.path == "/false-carrier-candidates" and json.loads(request.content) == QUERY
        return httpx.Response(200, json=payload)
    assert request_false_carrier_candidates(QUERY, transport=httpx.MockTransport(respond))["total"] == 1


@pytest.mark.parametrize("field,value", [("classification", "not_aircraft_carrier"), ("classification", "unknown"),
    ("observed_date", "2026-01-01"), ("observed_at", "2025-01-02T00:00:00Z"),
    ("observed_at", "2025-01-01T00:00:00+07:00")])
def test_wrong_scope_never_reaches_image_review(field, value):
    payload = positive_payload()
    payload["ships"][0][field] = value
    with pytest.raises(ValueError):
        request_false_carrier_candidates(QUERY, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))


@pytest.mark.parametrize("failure", ["missing-page", "duplicate-id", "missing-snapshot", "wrong-offset"])
def test_incomplete_or_mixed_pages_fail(failure):
    payload = positive_payload()
    if failure == "missing-page":
        payload["total"] = 2
    elif failure == "duplicate-id":
        payload["total"] = 2
        payload["ships"].append(deepcopy(payload["ships"][0]))
    elif failure == "missing-snapshot":
        payload.pop("source_snapshot_id")
    else:
        payload["offset"] = 1
    with pytest.raises(ValueError):
        request_false_carrier_candidates(QUERY, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
