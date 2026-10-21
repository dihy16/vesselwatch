"""Synthetic data only; URLs are placeholders, not real satellite images."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def today() -> date:
    return datetime.now(TIMEZONE).date()


def build_observations(reference_date: date) -> list[dict]:
    # Multiple observations per ship exercise deduplication and latest-label rules.
    samples = [
        ("SHIP_001", 6, "08:00:00", 310, 74, "aircraft_carrier", 0.92),
        ("SHIP_001", 6, "15:00:00", 310, 74, "not_aircraft_carrier", 0.81),
        ("SHIP_002", 6, "09:00:00", 280, 58, "aircraft_carrier", 0.87),
        ("SHIP_001", 1, "10:00:00", 312, 75, "aircraft_carrier", 0.94),
        ("SHIP_003", 1, "11:00:00", 265, 55, "unknown", None),
        ("SHIP_004", 0, "08:00:00", 335, 78, "aircraft_carrier", 0.89),
        ("SHIP_005", 0, "09:00:00", 180, 30, "not_aircraft_carrier", 0.96),
        ("SHIP_006", 10, "10:00:00", 350, 80, "aircraft_carrier", 0.83),
    ]
    observations = []
    for index, (ship_id, days_ago, time, length, width, label, confidence) in enumerate(samples, 1):
        observed_date = (reference_date - timedelta(days=days_ago)).isoformat()
        observations.append({
            "observation_id": f"OBS_{index:03d}",
            "ship_id": ship_id,
            "ship_url": f"https://example.com/ships/{ship_id}",
            "observed_date": observed_date,
            "observed_at": f"{observed_date}T{time}+07:00",
            "length_m": length,
            "width_m": width,
            "position": {"latitude": round(12 + index * 0.1, 2), "longitude": round(112 + index * 0.1, 2)},
            "classification": label,
            "confidence": confidence,
            "images": [{
                "image_id": f"IMG_{index:03d}",
                "url": 'https://pbs.twimg.com/media/E1Go05QWUAANrlq.jpg',
                "mime_type": "image/jpeg",
                "caption": f"Ảnh giả lập của {ship_id} ngày {observed_date}",
            }],
        })
    return observations
