"""Schemas and deterministic final flags for reference-based image comparisons."""

from typing import Literal
import base64

from pydantic import BaseModel, ConfigDict, Field, model_validator


def reference_review_content(target: bytes, library):
    """Build target-plus-all-reference pixels; no prediction or measured sizes enter vision."""
    def pixel_block(data):
        return {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(data).decode("ascii"), "detail": "high"}}
    content = [{"type": "text", "text": "TARGET — chỉ ảnh sau là đối tượng cần đánh giá."},
               pixel_block(target), {"type": "text", "text": "MÔ TẢ THAM KHẢO:\n" + library.description}]
    for image in library.images:
        content.extend([{"type": "text", "text": f"ẢNH MẪU reference_id={image.reference_id}; tên={image.name}"},
                        pixel_block(image.data)])
    return content


class ReferenceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    similarities: list[str] = Field(default_factory=list, max_length=10)
    differences: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def has_comparison(self):
        if not any(text.strip() for text in self.similarities + self.differences):
            raise ValueError("A reference citation needs an observed similarity or difference.")
        return self


class CarrierReferenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_quality: Literal["sufficient", "limited", "insufficient"]
    assessment: Literal["aircraft_carrier", "not_aircraft_carrier", "unknown"]
    visible_features: list[str] = Field(max_length=10)
    reference_evidence: list[ReferenceEvidence] = Field(max_length=100)
    limitations: list[str] = Field(max_length=10)
    reasoning: str = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def grounded_positive(self):
        if (self.image_quality == "sufficient" and self.assessment == "aircraft_carrier"
                and (not any(feature.strip() for feature in self.visible_features)
                     or not any(any(text.strip() for text in item.similarities) for item in self.reference_evidence))):
            raise ValueError("A positive reference match needs visible features and cited similarities.")
        return self


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
            "reference_images": [{"reference_id": image.reference_id, "name": image.name}
                                 for image in library.images],
            "saved_prediction": {"classification": observation["classification"],
                                 "carrier_score": observation["confidence"]},
            "is_ground_truth": False}


def run_reference_reviews(candidates, library, review_fn):
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
            results.append({"observation": observation, **reviewed})
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
