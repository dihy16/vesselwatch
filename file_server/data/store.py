"""In-memory snapshot structures and safe registered-image lookup."""

from dataclasses import dataclass
from pathlib import Path

from file_server.schemas.observations import Observation


def registered_image(root: Path, name: str) -> Path | None:
    """Resolve a crop path only inside the configured image directory."""
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate

@dataclass
class ObservationStore:
    observations: list[Observation]
    ships: dict[str, Observation]
    images: dict[str, tuple[str, str]]
    image_root: Path
    summary: dict
