"""Validate score-prioritized positives without silently applying a confidence cutoff."""

from file_server.services.label_review import REVIEW_ORDER, review_order
from ship_agent.clients.area_client import _request_review_candidates
from ship_agent.clients.hotspot_client import _distribution


def request_label_review_candidates(query, *, transport=None):
    result = _request_review_candidates(query, endpoint="carrier-label-review-candidates", transport=transport,
                                        matches=lambda row: row["classification"] == "aircraft_carrier")
    if result["status"] != "complete":
        return result
    try:
        if (result["review_order"] != REVIEW_ORDER or result["filters"]["classification"] != "aircraft_carrier"
                or any(result["filters"][key] != query[key] for key in ("observed_from", "observed_to"))
                or result["candidate_statistics"]["detection_count"] != result["total"]
                or result["ships"] != sorted(result["ships"], key=review_order)):
            raise ValueError("Invalid label-review scope, counts or order.")
        _distribution(result["candidate_statistics"], query)
        known = result["candidate_statistics"]["carrier_score"]["count"]
        expected_known = min(max(0, known - result["offset"]), len(result["ships"]))
        if any((row["confidence"] is not None) != (index < expected_known)
               for index, row in enumerate(result["ships"])):
            raise ValueError("Missing-score candidates must follow every known-score candidate.")
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Invalid label-review response.") from exc
    return result
