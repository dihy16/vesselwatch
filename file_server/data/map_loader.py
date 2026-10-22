"""Adapt the map's complete observation snapshot to the agent data API."""

from datetime import datetime
import math
import mimetypes
from urllib.parse import quote

from file_server.config import DataSettings
from file_server.data.map_bundle import load_bundle
from file_server.data.store import ObservationStore
from file_server.data.store import registered_image
from file_server.schemas.observations import ImageInfo, Observation
from file_server.schemas.observations import Position


def positive_dimension(value):
    return (float(value) if type(value) in (int, float) and math.isfinite(value)
            and value > 0 else None)


def load_map_store(settings: DataSettings) -> ObservationStore:
    data, provenance = load_bundle(settings.map_demo_dir)
    root = data.image_root.resolve()
    observations, images, ships = [], {}, {}
    base = settings.base_url.rstrip("/")
    for row in data.sources:
        identity = row["id"]
        metadata = row.get("metadata", {})
        score = row.get("prediction", {}).get("carrier_score")
        if score is not None and (type(score) not in (int, float)
                                  or not math.isfinite(score) or not 0 <= score <= 1):
            raise ValueError(f"Invalid map prediction score for {identity}.")
        classification = ("unknown" if score is None else "aircraft_carrier"
                          if score >= settings.carrier_threshold else "not_aircraft_carrier")
        captured = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
        name = row["image_path"]
        if registered_image(root, name) is None:
            raise ValueError(f"Missing map crop for {identity}.")
        image_id = "MAP_IMG_" + identity
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        images[image_id] = (name, mime)
        # A crop is an observation; preserve source identity separately.
        ship_id = str(metadata.get("source_id") or identity)
        observation = Observation(
            observation_id=identity, ship_id=ship_id,
            ship_url=f"{base}/ships/{quote(ship_id, safe='')}?observation_id={quote(identity, safe='')}",
            observed_date=captured.date().isoformat(), observed_at=captured.isoformat(),
            length_m=positive_dimension(metadata.get("length_m")),
            width_m=positive_dimension(metadata.get("width_m")),
            position=Position(latitude=row["latitude"], longitude=row["longitude"]),
            classification=classification, confidence=score,
            images=[ImageInfo(image_id=image_id, url=f"{base}/images/{quote(image_id, safe='')}",
                              mime_type=mime, caption=str(row.get("name", identity)))],
        )
        observations.append(observation)
        previous = ships.get(ship_id)
        if previous is None or observation.observed_at > previous.observed_at:
            ships[ship_id] = observation
    matched = sum(o.confidence is not None for o in observations)
    summary = {**provenance, "observation_count": len(observations), "prediction_count": matched,
               "unknown_count": len(observations) - matched,
               "missing_position_count": sum(o.position.latitude is None for o in observations),
               "carrier_threshold": settings.carrier_threshold,
               "possible_aircraft_carrier_count": sum(o.classification == "aircraft_carrier" for o in observations),
               "skipped": {}}
    return ObservationStore(observations, ships, images, root, summary)
