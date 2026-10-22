"""Combine one registered observation with independent reference-based visual evidence."""

from copy import deepcopy

from ship_agent.vision.schemas import CarrierReferenceReview
from ship_agent.workflows.reference_review import reference_review_result


def build_observation_evidence(observation, reviewed, library):
    if (reviewed.get("observation_id") != observation["observation_id"]
            or reviewed.get("reference_revision") != library.revision):
        raise ValueError("Visual evidence does not belong to this observation/reference set.")
    review = CarrierReferenceReview.model_validate(reviewed["visual_review"])
    unsupported_negative = review.assessment == "not_aircraft_carrier" and (
        not any(text.strip() for text in review.visible_features)
        or not any(any(text.strip() for text in item.differences) for item in review.reference_evidence))
    if unsupported_negative:
        review = review.model_copy(update={"assessment": "unknown"})
    canonical = reference_review_result(observation, review, library)
    visual = canonical["visual_review"]
    saved = observation["classification"]
    assessment = visual["assessment"]
    supporting, contradicting = [], []
    unresolved = list(visual["limitations"])
    if unsupported_negative:
        unresolved.append("Nhận xét nhãn âm chưa kèm đặc điểm nhìn thấy và khác biệt cụ thể dẫn đến ảnh mẫu.")
    if saved in {"aircraft_carrier", "not_aircraft_carrier"}:
        destination = supporting if saved == "aircraft_carrier" else contradicting
        destination.append({"source": "saved_prediction", "evidence_type": "model_output",
                            "classification": saved, "carrier_score": observation.get("confidence")})
    else:
        unresolved.append("Chưa có nhãn nhận dạng đã lưu cho observation này.")
    if assessment != "unknown":
        for evidence in visual["reference_evidence"]:
            if any(text.strip() for text in evidence["similarities"]):
                supporting.append({"source": "image", "evidence_type": "reference_comparison",
                                   "reference_id": evidence["reference_id"],
                                   "visible_features": visual["visible_features"],
                                   "details": evidence["similarities"]})
            if any(text.strip() for text in evidence["differences"]):
                contradicting.append({"source": "image", "evidence_type": "reference_comparison",
                                      "reference_id": evidence["reference_id"],
                                      "visible_features": visual["visible_features"],
                                      "details": evidence["differences"]})
    else:
        unresolved.append("Ảnh chưa đủ bằng chứng để đối chiếu kết luận tàu sân bay.")
    dimensions = {key: observation.get(key) for key in ("length_m", "width_m")}
    missing = [key for key, value in dimensions.items() if value is None]
    if missing:
        unresolved.append("Thiếu số đo: " + ", ".join(missing) + ".")
    comparison = ("inconclusive" if assessment == "unknown" or saved == "unknown"
                  else "agrees" if assessment == saved else "disagrees")
    return {"status": "complete", "review_mode": "carrier_reference_evidence",
            "observation_id": observation["observation_id"], "ship_id": observation["ship_id"],
            "image_id": observation["images"][0]["image_id"], "image_url": canonical["image_url"],
            **{key: reviewed[key] for key in ("image_width_px", "image_height_px",
                "vision_image_width_px", "vision_image_height_px", "image_resampling") if key in reviewed},
            "observation": deepcopy(observation), "measured_dimensions": dimensions,
            "saved_prediction": canonical["saved_prediction"], "visual_review": visual,
            "supporting_evidence": supporting, "contradicting_evidence": contradicting,
            "unresolved": list(dict.fromkeys(unresolved)), "comparison": comparison,
            "reference_revision": library.revision, "reference_images": canonical["reference_images"],
            "reference_description": library.description,
            "classifier_explanation_available": False, "is_ground_truth": False}
