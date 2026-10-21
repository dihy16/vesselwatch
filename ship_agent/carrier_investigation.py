"""Two-stage manual-review priorities without changing saved predictions."""

from file_server.carrier_investigation import LENGTH_THRESHOLD_M, dimension_priority
from .false_carrier_evidence import build_false_carrier_evidence
from .reference_review import run_reference_reviews


def _dimension_evidence(row):
    return {"observation": row, "observation_id": row["observation_id"], "ship_id": row["ship_id"],
            "image_url": row["images"][0]["url"] if row["images"] else None,
            "saved_prediction": {"classification": row["classification"], "carrier_score": row["confidence"]},
            "decision": "flagged", "flagged": True, "priority": 1,
            "flag_reason": "length_below_300m", "visual_review": None,
            "reference_comparison_performed": False, "is_confirmed_error": False, "is_ground_truth": False,
            "dimension_evidence": {"length_m": row["length_m"], "operator": "<", "threshold_m": LENGTH_THRESHOLD_M}}


def run_carrier_investigation(candidates, *, load_library, create_reviewer):
    """Lazy vision setup: short targets need neither pixels nor a reference bank."""
    rows = candidates["ships"]
    if any(row["classification"] != "aircraft_carrier" for row in rows):
        raise ValueError("Investigation requires saved carrier-positive observations.")
    short = [row for row in rows if dimension_priority(row)]
    visual_rows = [row for row in rows if not dimension_priority(row)]
    flags = [_dimension_evidence(row) for row in short]
    unflagged, errors, library = [], [], None
    if visual_rows:
        try:
            library = load_library()
            reviewer = create_reviewer()
        except Exception:
            # Keep independent dimension results; never leak provider configuration/bodies.
            errors = [{"observation_id": row["observation_id"], "error": "reference_review_unavailable"}
                      for row in visual_rows]
        else:
            page = run_reference_reviews({**candidates, "ships": visual_rows, "offset": 0,
                                          "total": len(visual_rows), "limit": len(visual_rows)},
                                         library, reviewer, result_builder=build_false_carrier_evidence)
            flags.extend({**item, "priority": 2, "reference_comparison_performed": True}
                         for item in page["flags"])
            unflagged = [{**item, "reference_comparison_performed": True} for item in page["unflagged"]]
            errors = page["errors"]
    reviewed = len(visual_rows) - len(errors)
    total, offset, selected = candidates["total"], candidates["offset"], len(rows)
    complete = offset == 0 and selected == total and not errors
    processed = len(short) + reviewed
    status = "complete" if complete else "failed" if errors and not processed else "partial"
    if not rows:
        status = "no_candidates" if total == 0 else "empty_page"
    result = {"status": status, "investigation": "carrier_manual_review_priorities",
              "filters": candidates["filters"], "source_snapshot_id": candidates["source_snapshot_id"],
              "total_candidates": total, "dimension_candidate_count": candidates["dimension_candidate_count"],
              "visual_candidate_count": candidates["visual_candidate_count"],
              "length_threshold_m": LENGTH_THRESHOLD_M, "offset": offset, "limit": candidates["limit"],
              "selected_count": selected, "dimension_screened_count": len(short),
              "reviewed_count": reviewed, "processed_count": processed, "failed_count": len(errors),
              "coverage_complete": complete,
              "next_offset": offset + selected if offset + selected < total else None,
              "flagged_count": len(flags), "priority_1_count": len(short),
              "priority_2_count": len(flags) - len(short), "flags": flags, "unflagged": unflagged,
              "errors": errors, "reference_comparison_performed": reviewed > 0,
              "reference_revision": library.revision if library is not None else None,
              "reference_count": len(library.images) if library is not None else 0,
              "count_unit": "detections", "is_ground_truth": False}
    return result, library
