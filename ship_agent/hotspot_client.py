"""Validate geographic counts and bind detailed reviews to an exact DBSCAN report."""

from datetime import date, datetime, timedelta
from math import isfinite
import re

from file_server.carrier_hotspots import ALGORITHM
from .area_client import _request_query, _request_review_candidates, _validate_investigation_groups


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Invalid hotspot count.")
    return value


def _distribution(item, query):
    total = _count(item["detection_count"])
    _count(item["active_day_count"])
    first, last = date.fromisoformat(query["observed_from"]), date.fromisoformat(query["observed_to"])
    days = [(first + timedelta(days=index)).isoformat() for index in range((last - first).days + 1)]
    if ([entry["date"] for entry in item["daily_stats"]] != days
            or sum(_count(entry["count"]) for entry in item["daily_stats"]) != total
            or item["active_day_count"] != sum(entry["count"] > 0 for entry in item["daily_stats"])):
        raise ValueError("Invalid hotspot date distribution.")
    if total:
        timestamps = [datetime.fromisoformat(item[key].replace("Z", "+00:00"))
                      for key in ("first_observed_at", "last_observed_at")]
        if (any(stamp.tzinfo is None or stamp.utcoffset() != timedelta(0)
                or not first <= stamp.date() <= last for stamp in timestamps) or timestamps[0] > timestamps[1]):
            raise ValueError("Invalid hotspot observation times.")
    elif item["first_observed_at"] is not None or item["last_observed_at"] is not None:
        raise ValueError("Empty statistics must not invent observation times.")
    bounds = item["geographic_extent"]
    if bounds is not None:
        if (any(type(bounds[key]) not in (int, float) or not isfinite(bounds[key])
                for key in ("south", "north", "west", "east"))
                or not -90 <= bounds["south"] <= bounds["north"] <= 90
                or not -180 <= bounds["west"] <= 180 or not -180 <= bounds["east"] <= 180
                or bounds["crosses_antimeridian"] is not (bounds["west"] > bounds["east"])):
            raise ValueError("Invalid hotspot geographic extent.")
    for key in ("length_m", "width_m", "carrier_score"):
        stats = item[key]
        if _count(stats["count"]) + _count(stats["missing_count"]) != total:
            raise ValueError("Invalid hotspot measurement coverage.")
        values = [stats[field] for field in ("min", "max", "mean", "median")]
        if stats["count"] == 0:
            if any(value is not None for value in values):
                raise ValueError("Empty statistics must not invent measurements.")
        elif (any(type(value) not in (int, float) or not isfinite(value) for value in values)
              or not stats["min"] <= stats["mean"] <= stats["max"]
              or not stats["min"] <= stats["median"] <= stats["max"]
              or (key == "carrier_score" and not 0 <= stats["min"] <= stats["max"] <= 1)
              or (key != "carrier_score" and stats["min"] <= 0)):
            raise ValueError("Invalid hotspot statistics.")
    if (sum(_count(item["length_groups"][key]) for key in ("below_300m", "at_least_300m", "missing")) != total
            or item["length_groups"]["missing"] != item["length_m"]["missing_count"]):
        raise ValueError("Invalid hotspot size groups.")
    histogram = item["carrier_score"]["histogram"]
    if (len(histogram) != 10 or sum(_count(entry["count"]) for entry in histogram) != item["carrier_score"]["count"]
            or any(entry["lower"] != index / 10 or entry["upper"] != (index + 1) / 10
                   or entry["upper_inclusive"] is not (index == 9) for index, entry in enumerate(histogram))):
        raise ValueError("Invalid carrier-score histogram.")


def request_carrier_hotspots(query, *, transport=None):
    result = _request_query(query, endpoint="carrier-hotspots", collection="clusters", transport=transport)
    if result["status"] != "complete":
        return result
    try:
        for key in ("report_id", "source_snapshot_id"):
            if not isinstance(result[key], str) or not re.fullmatch(r"[a-f0-9]{64}", result[key]):
                raise ValueError("Missing hotspot snapshot identity.")
        if result["algorithm"] != ALGORITHM:
            raise ValueError("Unexpected geographic clustering parameters.")
        if (result["filters"].get("classification") != "aircraft_carrier"
                or any(result["filters"].get(key) != query[key] for key in ("observed_from", "observed_to"))):
            raise ValueError("Unexpected hotspot filters.")
        for key in ("total_detections", "located_count", "missing_position_count", "unlocated_in_date_range_count",
                    "clustered_detection_count", "noise_count"):
            _count(result[key])
        expected = min(max(0, result["total"] - query.get("offset", 0)), query.get("limit", 20))
        if (result["located_count"] + result["missing_position_count"] != result["total_detections"]
                or result["clustered_detection_count"] + result["noise_count"] != result["located_count"]
                or len(result["clusters"]) != expected or result["limit"] != query.get("limit", 20)
                or result["offset"] != query.get("offset", 0)
                or result["summary"]["detection_count"] != result["total_detections"]):
            raise ValueError("Incomplete hotspot counts or page.")
        _distribution(result["summary"], query)
        ids = set()
        for index, cluster in enumerate(result["clusters"]):
            if (not isinstance(cluster["cluster_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", cluster["cluster_id"])
                    or cluster["cluster_id"] in ids or cluster["rank"] != result["offset"] + index + 1
                    or cluster["detection_count"] < ALGORITHM["min_samples"]
                    or cluster["geographic_extent"] is None):
                raise ValueError("Invalid hotspot cluster identity or rank.")
            ids.add(cluster["cluster_id"])
            _distribution(cluster, query)
        counts = [cluster["detection_count"] for cluster in result["clusters"]]
        if counts != sorted(counts, reverse=True) or sum(counts) > result["clustered_detection_count"]:
            raise ValueError("Invalid hotspot ranking.")
        if result["offset"] == 0 and expected == result["total"] and sum(counts) != result["clustered_detection_count"]:
            raise ValueError("Hotspot clusters do not cover the clustered detections.")
        next_offset = result["offset"] + result["limit"] if result["offset"] + result["limit"] < result["total"] else None
        if result["next_offset"] != next_offset:
            raise ValueError("Invalid hotspot continuation.")
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Invalid hotspot response.") from exc
    return result


def request_carrier_hotspot_candidates(query, *, transport=None):
    result = _request_review_candidates(query, endpoint="carrier-hotspot-candidates", transport=transport,
                                        matches=lambda row: row["classification"] == "aircraft_carrier")
    if result["status"] == "complete" and (result.get("report_id") != query["report_id"]
                                           or result.get("cluster_id") != query["cluster_id"]):
        raise ValueError("Hotspot membership is from a different report or cluster.")
    return _validate_investigation_groups(result)
