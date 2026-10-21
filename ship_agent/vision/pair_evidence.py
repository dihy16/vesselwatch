"""Compare opposite-label observations through one shared carrier reference set."""

import math

from file_server.services.observation_analysis import valid_dimensions
from ship_agent.vision.observation_evidence import build_observation_evidence


def validate_observation_pair(first, second, similarity_tolerance_pct=10):
    if (type(similarity_tolerance_pct) not in (int, float) or not math.isfinite(similarity_tolerance_pct)
            or not 0 <= similarity_tolerance_pct <= 100):
        raise ValueError("Sai lệch kích thước phải từ 0 đến 100%.")
    if first["observation_id"] == second["observation_id"]:
        raise ValueError("Cần hai observation_id khác nhau.")
    if {first["classification"], second["classification"]} != {"aircraft_carrier", "not_aircraft_carrier"}:
        raise ValueError("Câu 15 cần một observation nhãn aircraft_carrier và một not_aircraft_carrier.")
    if not valid_dimensions(first) or not valid_dimensions(second):
        raise ValueError("Cần đủ số đo chiều dài và rộng của cả hai observations.")
    differences = {key: 100 * abs(first[key] - second[key]) / max(first[key], second[key])
                   for key in ("length_m", "width_m")}
    if any(value > similarity_tolerance_pct + 1e-9 for value in differences.values()):
        raise ValueError("Cặp observations vượt sai lệch kích thước đã chọn; lấy cặp phù hợp từ câu 12.")
    return {"similarity_tolerance_pct": similarity_tolerance_pct,
            "formula": "100 * abs(a-b) / max(a,b)",
            "length_difference_pct": differences["length_m"], "width_difference_pct": differences["width_m"]}


def build_pair_evidence(first, second, first_reviewed, second_reviewed, library, similarity_tolerance_pct=10):
    dimensions = validate_observation_pair(first, second, similarity_tolerance_pct)
    first_evidence = build_observation_evidence(first, first_reviewed, library)
    second_evidence = build_observation_evidence(second, second_reviewed, library)
    assessments = [item["visual_review"]["assessment"] for item in (first_evidence, second_evidence)]
    if "unknown" in assessments:
        outcome = "inconclusive"
    elif assessments[0] == assessments[1]:
        outcome = "visual_reviews_do_not_support_label_difference"
    elif all(item["comparison"] == "agrees" for item in (first_evidence, second_evidence)):
        outcome = "visual_evidence_consistent_with_label_difference"
    else:
        outcome = "visual_evidence_opposes_label_assignment"
    for item in (first_evidence, second_evidence):
        item.pop("reference_description", None)  # Shared once, not repeated in the model context.
    return {"status": "complete", "review_mode": "pair_carrier_reference_evidence",
            "first_observation": first_evidence, "second_observation": second_evidence,
            "dimension_comparison": dimensions, "outcome": outcome,
            "reference_revision": library.revision, "reference_count": len(library.images),
            "reference_description": library.description,
            "can_explain_label_difference": outcome == "visual_evidence_consistent_with_label_difference",
            "is_same_vessel_established": False, "classifier_explanation_available": False,
            "is_ground_truth": False}
