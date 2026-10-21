"""The investigation client validates full counts and the dimension-first page boundary."""

from copy import deepcopy
import json

import httpx
import pytest

from ship_agent.area_client import request_carrier_investigation_candidates
from tests.integration.test_false_carrier_client import positive_payload
from tests.integration.test_missed_carrier_client import QUERY


def investigation_payload():
    return {**positive_payload(), "dimension_candidate_count": 0, "visual_candidate_count": 1,
            "length_threshold_m": 300}


def test_investigation_endpoint_and_missing_length_routed_to_images():
    def respond(request):
        assert request.url.path == "/carrier-investigation-candidates"
        assert json.loads(request.content) == QUERY
        return httpx.Response(200, json=investigation_payload())
    result = request_carrier_investigation_candidates(QUERY, transport=httpx.MockTransport(respond))
    assert result["dimension_candidate_count"] == 0


@pytest.mark.parametrize("failure", ["wrong-total", "missing-count", "negative-count", "bool-count",
                                    "wrong-threshold", "short-after-boundary", "long-before-boundary"])
def test_cannot_silently_mix_groups_or_counts(failure):
    payload = investigation_payload()
    if failure == "wrong-total":
        payload["dimension_candidate_count"] = 1
    elif failure == "missing-count":
        payload.pop("visual_candidate_count")
    elif failure == "negative-count":
        payload.update(dimension_candidate_count=-1, visual_candidate_count=2)
    elif failure == "bool-count":
        payload["dimension_candidate_count"] = False
    elif failure == "wrong-threshold":
        payload["length_threshold_m"] = 250
    elif failure == "short-after-boundary":
        payload["ships"][0]["length_m"] = 299
    else:
        payload.update(dimension_candidate_count=1, visual_candidate_count=0)
    with pytest.raises(ValueError):
        request_carrier_investigation_candidates(QUERY,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))


def test_page_crossing_group_boundary():
    payload = investigation_payload()
    large = deepcopy(payload["ships"][0])
    large["observation_id"] = "large"
    large["length_m"] = 300
    payload["ships"][0]["length_m"] = 299
    payload.update(total=3, dimension_candidate_count=2, visual_candidate_count=1,
                   limit=2, offset=1, ships=payload["ships"] + [large])
    result = request_carrier_investigation_candidates({**QUERY, "limit": 2, "offset": 1},
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    assert result["total"] == 3 and len(result["ships"]) == 2
