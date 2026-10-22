"""Load map-bundle or Telegram observations for the shared data API."""

import hashlib
import mimetypes
from urllib.parse import quote

from file_server.config import DataSettings
from file_server.data.caption import SHIP_PATTERN, clean_caption, parse_caption
from file_server.data.json_io import read_records
from file_server.data.predictions import load_predictions, image_filename
from file_server.data.store import ObservationStore, registered_image
from file_server.schemas.observations import Observation, Position, ImageInfo


def load_store(settings: DataSettings) -> ObservationStore:
    if settings.data_source == "map_bundle":
        from file_server.data.map_loader import load_map_store
        return load_map_store(settings)
    predictions, prediction_metadata = load_predictions(settings.predictions_path)
    root = settings.image_root.resolve()
    if not root.is_dir():
        raise ValueError(f"Telegram image directory does not exist: {root}")
    observations = []
    images = {}
    seen = {}
    counts = dict(missing_detection_id=0, missing_image=0,
                  duplicate_image=0, unsupported_image=0, missing_prediction=0)
    for message in read_records(settings.telegram_path):
        caption = message.get("caption", "")
        cleaned = clean_caption(caption) if isinstance(caption, str) else ""
        match = SHIP_PATTERN.search(cleaned)
        if not match:
            counts["missing_detection_id"] += 1
            continue
        source_id = match.group(1).strip()
        # Telegram exports use telegram_data/images/<filename>, while root is images/.
        value = message.get("image")
        name = image_filename(value)
        if not name or registered_image(root, name) is None:
            counts["missing_image"] += 1
            continue
        mime = mimetypes.guess_type(name)[0]
        if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/tiff", "image/bmp"}:
            counts["unsupported_image"] += 1
            continue
        if name in seen:
            if seen[name] != source_id:
                raise ValueError(f"Telegram image {name} links to multiple detection IDs.")
            counts["duplicate_image"] += 1
            continue
        seen[name] = source_id
        prediction = predictions.get(name)
        if prediction is None:
            counts["missing_prediction"] += 1
            continue
        try:
            metadata = parse_caption(caption)
            captured = metadata.observed_at
            score = prediction.score
            classification = prediction.classification
            # Filename identity makes separate Telegram images separate ships.
            token = hashlib.sha256(name.encode("utf-8")).hexdigest()
            ship_id, image_id = metadata.source_id, f"IMG_{token}"
            base = settings.base_url.rstrip("/")
            observation = Observation(
                observation_id=f"OBS_{token}", ship_id=ship_id,
                ship_url=f"{base}/ships/{quote(ship_id, safe='')}?observation_id=OBS_{token}",
                observed_date=captured.date().isoformat(), observed_at=captured.isoformat(),
                length_m=metadata.length_m, width_m=metadata.width_m,
                position=Position(latitude=metadata.latitude, longitude=metadata.longitude),
                classification=classification, confidence=score,
                images=[ImageInfo(image_id=image_id, url=f"{base}/images/{image_id}",
                                  mime_type=mime, caption=caption)],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid Telegram observation for {name} (detection {source_id}): {exc}"
            ) from exc
        observations.append(observation)
        images[image_id] = (name, mime)
    observations.sort(key=lambda observation: observation.ship_id)
    matched = sum(observation.confidence is not None for observation in observations)
    summary = {"observation_count": len(observations), "prediction_count": matched,
               "unknown_count": len(observations) - matched, "skipped": counts,
               **prediction_metadata}
    # A caption ID may occur in several images; direct links select the exact observation.
    ships = {}
    for observation in observations:
        previous = ships.get(observation.ship_id)
        if previous is None or observation.observed_at > previous.observed_at:
            ships[observation.ship_id] = observation
    return ObservationStore(observations, ships, images, root, summary)
