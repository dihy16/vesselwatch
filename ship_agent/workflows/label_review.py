"""Group independent image evidence and recommend manual labels only for grounded conflicts."""

from ship_agent.vision.false_carrier_evidence import build_false_carrier_evidence
from ship_agent.workflows.reference_review import run_reference_reviews


REVIEW_GROUPS = ("suspected_false_positive", "reference_consistent", "inconclusive",
                 "insufficient_image", "review_failed")


def build_label_review(observation, reviewed, library):
    evidence = build_false_carrier_evidence(observation, reviewed, library)
    decision = evidence["decision"]
    group = {"flagged": "suspected_false_positive", "not_flagged": "reference_consistent",
             "inconclusive": "inconclusive", "insufficient_image": "insufficient_image"}[decision]
    visual = evidence["visual_review"]
    factors = []
    if group in {"suspected_false_positive", "reference_consistent"}:
        field = "differences" if group == "suspected_false_positive" else "similarities"
        for reference in visual["reference_evidence"]:
            if any(detail.strip() for detail in reference[field]):
                factors.append({"factor": "reference_" + field, "reference_id": reference["reference_id"],
                                "visible_features": visual["visible_features"], "details": reference[field]})
    else:
        factors.append({"factor": "insufficient_image_detail" if group == "insufficient_image" else "inconclusive_reference_evidence",
                        "image_quality": visual["image_quality"], "limitations": evidence["unresolved"]})
    return {**evidence, "review_group": group, "review_factors": factors,
            "annotation_recommended": evidence["flagged"], "label_applied": False}


def _unreviewed_result(candidates, errors):
    total, offset, selected = candidates["total"], candidates["offset"], len(candidates["ships"])
    return {"status": "failed" if errors else "no_candidates" if total == 0 else "empty_page",
            "filters": candidates["filters"], "source_snapshot_id": candidates["source_snapshot_id"],
            "total_candidates": total, "offset": offset, "limit": candidates["limit"],
            "reviewed_count": 0, "failed_count": len(errors), "coverage_complete": total == 0,
            "next_offset": offset + selected if offset + selected < total else None,
            "flagged_count": 0, "flags": [], "unflagged": [], "errors": errors,
            "reference_revision": None, "reference_count": 0, "count_unit": "detections", "is_ground_truth": False}


def run_label_investigation(candidates, *, load_library, create_reviewer):
    """All selected positives are read, including short and high-score targets."""
    rows, library = candidates["ships"], None
    if any(row["classification"] != "aircraft_carrier" for row in rows):
        raise ValueError("BR 19 requires saved carrier-positive observations.")
    if not rows:
        result = _unreviewed_result(candidates, [])
    else:
        try:
            library = load_library()
            reviewer = create_reviewer()
        except Exception:
            result = _unreviewed_result(candidates, [{"observation_id": row["observation_id"],
                                                    "error": "reference_review_unavailable"} for row in rows])
        else:
            result = run_reference_reviews(candidates, library, reviewer, result_builder=build_label_review)
    members = {group: [] for group in REVIEW_GROUPS}
    for item in result["flags"] + result["unflagged"]:
        members[item["review_group"]].append(item["observation_id"])
    members["review_failed"] = [item["observation_id"] for item in result["errors"]]
    result.update(investigation="carrier_label_review", review_order=candidates["review_order"],
                  candidate_statistics=candidates["candidate_statistics"], selected_count=len(rows),
                  group_counts={group: len(ids) for group, ids in members.items()}, group_observation_ids=members,
                  annotation_candidates=[{"observation_id": item["observation_id"], "ship_id": item["ship_id"],
                      "image_url": item["image_url"], "reason": "grounded_reference_disagreement",
                      "recommended_action": "manual_label_verification", "label_applied": False}
                      for item in result["flags"]], annotation_candidate_count=result["flagged_count"],
                  classifier_explanation_available=False, reference_comparison_performed=result["reviewed_count"] > 0)
    return result, library
