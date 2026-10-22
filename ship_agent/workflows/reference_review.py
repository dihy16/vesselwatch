"""Schemas and deterministic final flags for reference-based image comparisons."""

import base64

from file_server.media.image_assets import ImageVariant, prepare_vision_image
from ship_agent.vision.schemas import CarrierReferenceReview


def reference_review_content(target: bytes | ImageVariant, library):
    """Build target-plus-all-reference pixels; no prediction or measured sizes enter vision."""
    def pixel_block(data):
        return {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(data).decode("ascii"), "detail": "high"}}
    prepared = target if isinstance(target, ImageVariant) else prepare_vision_image(target)
    content = [{"type": "text", "text": "TARGET — chỉ ảnh sau là đối tượng cần đánh giá. " + prepared.description()},
               pixel_block(prepared.data), {"type": "text", "text": "MÔ TẢ THAM KHẢO:\n" + library.description}]
    for image in library.images:
        prepared = prepare_vision_image(image.data)
        content.extend([{"type": "text", "text": f"ẢNH MẪU reference_id={image.reference_id}; tên={image.name}. " + prepared.description()},
                        pixel_block(prepared.data)])
    return content


def reference_review_result(observation, review: CarrierReferenceReview, library):
    known_ids = {image.reference_id for image in library.images}
    if any(item.reference_id not in known_ids for item in review.reference_evidence):
        raise ValueError("Visual review cited an unknown reference image.")
    if review.image_quality != "sufficient":
        review = review.model_copy(update={"assessment": "unknown"})
        decision = "insufficient_image"
    elif review.assessment == "aircraft_carrier":
        decision = "flagged"
    elif review.assessment == "unknown":
        decision = "inconclusive"
    else:
        decision = "not_flagged"
    return {"observation_id": observation["observation_id"], "ship_id": observation["ship_id"],
            "image_url": observation["images"][0]["url"], "decision": decision,
            "flagged": decision == "flagged", "visual_review": review.model_dump(),
            "reference_revision": library.revision,
            "reference_images": library.display_images(),
            "saved_prediction": {"classification": observation["classification"],
                                 "carrier_score": observation["confidence"]},
            "is_ground_truth": False}


def run_reference_reviews(candidates, library, review_fn, *, result_builder=None):
    """Review every selected candidate; failed reviews never become clean negatives."""
    results, errors = [], []
    for observation in candidates["ships"]:
        try:
            reviewed = review_fn(observation, library)
            expected = reference_review_result(observation,
                CarrierReferenceReview.model_validate(reviewed["visual_review"]), library)
            if (reviewed["observation_id"] != observation["observation_id"]
                    or reviewed["reference_revision"] != library.revision
                    or reviewed["decision"] != expected["decision"]
                    or reviewed["flagged"] != expected["flagged"]):
                raise ValueError("Review identity or decision mismatch.")
            result = result_builder(observation, reviewed, library) if result_builder is not None else reviewed
            results.append({"observation": observation, **result})
        except Exception:
            # Provider exceptions may include pixels, credentials or request bodies.
            errors.append({"observation_id": observation["observation_id"], "error": "image_review_failed"})
    total, offset = candidates["total"], candidates["offset"]
    selected = len(candidates["ships"])
    has_more = offset + selected < total
    complete = not errors and offset == 0 and selected == total
    return {"status": "failed" if errors and not results else "complete" if complete else "partial",
            "filters": candidates["filters"], "source_snapshot_id": candidates.get("source_snapshot_id"),
            "reference_revision": library.revision, "reference_count": len(library.images),
            "total_candidates": total, "offset": offset, "limit": candidates["limit"],
            "reviewed_count": len(results), "failed_count": len(errors), "coverage_complete": complete,
            "next_offset": offset + selected if has_more else None,
            "flagged_count": sum(item["flagged"] for item in results),
            "flags": [item for item in results if item["flagged"]],
            "unflagged": [item for item in results if not item["flagged"]], "errors": errors,
            "count_unit": "detections", "is_ground_truth": False}
