"""Deterministic size/prediction comparisons over complete observation snapshots."""

from bisect import bisect_left, bisect_right
import math

from .area_models import AreaQueryInput, ObservationAnalysisRequest
from .spatial import query_observations


def analysis_filters(request: ObservationAnalysisRequest) -> AreaQueryInput:
    values = request.model_dump(include=set(AreaQueryInput.model_fields))
    if request.analysis == "dimension_mismatch":
        values["classification"] = "not_aircraft_carrier"
        if all(values[key] is None for key in ("min_length_m", "max_length_m", "length_gt_m")):
            values.update(min_length_m=250, max_length_m=350)
        if values["min_width_m"] is None and values["max_width_m"] is None:
            values.update(min_width_m=50, max_width_m=80)
    return AreaQueryInput.model_validate(values)


def valid_dimensions(row):
    return all(type(row.get(key)) in (int, float) and math.isfinite(row[key])
               and row[key] > 0 for key in ("length_m", "width_m"))


def analyze_observations(rows, request: ObservationAnalysisRequest, geometry=None):
    query = analysis_filters(request)
    selected = query_observations(rows, query, geometry)
    common = {"analysis": request.analysis, "filters": query.model_dump(),
              "limit": query.limit, "offset": query.offset}
    if request.analysis == "dimension_mismatch":
        return {**common, "count_unit": "detections", "total": len(selected),
                "ships": selected[query.offset:query.offset + query.limit],
                "dimension_rule": "Khoảng kích thước là tiêu chí lọc, không phải xác nhận loại tàu."}

    known = [r for r in selected if r["classification"] in ("aircraft_carrier", "not_aircraft_carrier")]
    usable = [r for r in known if valid_dimensions(r)]
    positives = sorted((r for r in usable if r["classification"] == "aircraft_carrier"),
                       key=lambda r: (r["length_m"], r["observation_id"]))
    negatives = sorted((r for r in usable if r["classification"] == "not_aircraft_carrier"),
                       key=lambda r: (r["length_m"], r["observation_id"]))
    lengths = [r["length_m"] for r in negatives]
    tolerance = request.similarity_tolerance_pct
    factor = 1 - tolerance / 100
    total, pairs = 0, []
    for positive in positives:
        # Bound candidates by length before comparing widths; each opposite-label pair occurs once.
        lower = positive["length_m"] * factor
        upper = positive["length_m"] / factor if factor > 0 else math.inf
        start, stop = bisect_left(lengths, lower - 1e-9), bisect_right(lengths, upper + 1e-9)
        for index in range(start, stop):
            negative = negatives[index]
            differences = {key: 100 * abs(positive[key] - negative[key]) / max(positive[key], negative[key])
                           for key in ("length_m", "width_m")}
            if any(value > tolerance + 1e-9 for value in differences.values()):
                continue
            if query.offset <= total < query.offset + query.limit:
                pairs.append({"aircraft_carrier": positive, "not_aircraft_carrier": negative,
                              "length_difference_pct": differences["length_m"],
                              "width_difference_pct": differences["width_m"]})
            total += 1
    return {**common, "count_unit": "observation_pairs", "total": total, "pairs": pairs,
            "comparison_rule": {"similarity_tolerance_pct": tolerance,
                                "formula": "100 * abs(a-b) / max(a,b)", "dimensions": ["length_m", "width_m"]},
            "candidate_observation_count": len(usable),
            "excluded_unknown_classification_count": len(selected) - len(known),
            "excluded_missing_dimensions_count": len(known) - len(usable)}
