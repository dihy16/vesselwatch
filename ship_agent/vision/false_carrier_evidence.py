"""Flag saved carrier positives only on sufficient, grounded non-carrier evidence."""

from ship_agent.vision.observation_evidence import build_observation_evidence


def build_false_carrier_evidence(observation, reviewed, library):
    if observation["classification"] != "aircraft_carrier":
        raise ValueError("Positive-label audit requires an aircraft_carrier prediction.")
    # BR 13 canonicalization checks IDs/revision/citations and rejects unsupported negatives.
    evidence = build_observation_evidence(observation, reviewed, library)
    visual = evidence["visual_review"]
    if visual["image_quality"] != "sufficient":
        decision = "insufficient_image"
    elif visual["assessment"] == "unknown":
        decision = "inconclusive"
    elif visual["assessment"] == "not_aircraft_carrier":
        decision = "flagged"
    else:
        decision = "not_flagged"
    return {**evidence, "review_mode": "false_carrier_reference_evidence", "decision": decision,
            "flagged": decision == "flagged", "flag_reason": "suspected_non_carrier" if decision == "flagged" else None,
            "is_confirmed_error": False}
