"""Complete review pages retain UTC/source scope, score order and full candidate statistics."""

from copy import deepcopy
import json

import httpx
import pytest

from file_server.services.label_review import label_review_candidates
from ship_agent.clients.label_review_client import request_label_review_candidates
from tests.file_server.test_label_review_candidates import scope
from tests.integration.test_false_carrier_client import positive_payload


def payload():
    base = positive_payload()["ships"][0]
    rows = []
    for identity, score, length in (("low", .5, 100), ("high", 1, 300), ("missing", None, None)):
        item = deepcopy(base)
        item.update(observation_id=identity, confidence=score, length_m=length)
        rows.append(item)
    return {"status": "complete", "area_id": "a" * 32, "map_url": "http://public/map",
            "source_snapshot_id": "b" * 64, **label_review_candidates(rows, scope())}


def test_endpoint_all_positive_scores_and_missing_values():
    def respond(request):
        assert request.url.path == "/carrier-label-review-candidates" and json.loads(request.content) == scope().model_dump()
        return httpx.Response(200, json=payload())
    result = request_label_review_candidates(scope().model_dump(), transport=httpx.MockTransport(respond))
    assert [item["observation_id"] for item in result["ships"]] == ["low", "high", "missing"]


@pytest.mark.parametrize("failure", ["order", "missing-order", "policy", "counts", "dates", "snapshot", "wrong-label", "truncated"])
def test_incomplete_mixed_or_reordered_results_are_rejected(failure):
    result = payload()
    if failure == "order":
        result["ships"][0], result["ships"][1] = result["ships"][1], result["ships"][0]
    elif failure == "missing-order":
        result["ships"] = list(reversed(result["ships"]))
    elif failure == "policy":
        result["review_order"] = "size_first"
    elif failure == "counts":
        result["candidate_statistics"]["detection_count"] += 1
    elif failure == "dates":
        result["filters"]["observed_to"] = "2026-01-01"
    elif failure == "snapshot":
        result.pop("source_snapshot_id")
    elif failure == "wrong-label":
        result["ships"][0]["classification"] = "not_aircraft_carrier"
    else:
        result["ships"].pop()
    with pytest.raises(ValueError):
        request_label_review_candidates(scope().model_dump(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result)))


def test_missing_scores_cannot_appear_before_all_known_scores_across_pages():
    result = payload()
    result.update(ships=result["ships"][-1:], limit=1, offset=0)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=result))
    with pytest.raises(ValueError):
        request_label_review_candidates(scope(limit=1).model_dump(), transport=transport)
    result["offset"] = 2
    assert request_label_review_candidates(scope(limit=1, offset=2).model_dump(), transport=transport)["ships"][0]["confidence"] is None
