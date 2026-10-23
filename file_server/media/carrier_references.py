"""Immutable reference-library snapshots loaded from the configured local folder."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path

from file_server.media.image_assets import MAX_IMAGE_BYTES, normalize_image, image_preview_url


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
MAX_DESCRIPTION_BYTES = 65536
REFERENCE_LABELS = {"aircraft_carrier", "not_aircraft_carrier"}


@dataclass(frozen=True)
class ReferenceImage:
    reference_id: str
    name: str
    data: bytes
    width: int
    height: int
    url: str | None = field(default=None, compare=False, repr=False)
    label: str = "aircraft_carrier"

    def __post_init__(self):
        if not isinstance(self.label, str) or self.label not in REFERENCE_LABELS:
            raise ValueError("Invalid reference label.")


def reference_id(name: str, data: bytes) -> str:
    return sha256(name.encode("utf-8") + b"\0" + data).hexdigest()[:32]


def library_revision(description: str, images) -> str:
    payload = {"description": description,
               "images": sorted((image.name, image.reference_id) for image in images)}
    # Preserve legacy positive-only revisions, binding mixed-library labels to the snapshot.
    if any(image.label != "aircraft_carrier" for image in images):
        payload["labels"] = sorted((image.reference_id, image.label) for image in images)
    return sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ReferenceLibrary:
    description: str
    images: tuple[ReferenceImage, ...]
    revision: str

    def display_images(self, base_url: str | None = None):
        records = []
        for image in self.images:
            record = {"reference_id": image.reference_id, "name": image.name,
                      "width": image.width, "height": image.height, "label": image.label}
            url = image.url or (base_url.rstrip("/") +
                f"/carrier-references/images/{image.reference_id}?revision={self.revision}" if base_url else None)
            if url:
                record.update(url=url, preview_url=image_preview_url(url))
            records.append(record)
        return records

    def manifest(self, base_url: str):
        return {"description": self.description, "revision": self.revision,
                "images": [{**record, "mime_type": "image/png"} for record in self.display_images(base_url)]}


def _read_bounded(path: Path, limit: int):
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Reference asset exceeds the size limit.")
    return data


def load_reference_library(directory: Path) -> ReferenceLibrary:
    root = directory.resolve()
    description_path = root / "description.md"
    if not description_path.is_file() or description_path.is_symlink():
        raise ValueError("Cần description.md và ảnh mẫu thật trong CARRIER_REFERENCE_DIR.")
    description = _read_bounded(description_path, MAX_DESCRIPTION_BYTES).decode("utf-8-sig").strip()
    if not description:
        raise ValueError("description.md chưa có mô tả tàu sân bay.")
    labels_path = root / "labels.json"
    labels = None
    if labels_path.is_symlink():
        raise ValueError("Reference labels must not be a symlink.")
    if labels_path.exists():
        labels = json.loads(_read_bounded(labels_path, MAX_DESCRIPTION_BYTES).decode("utf-8-sig"))
        if (not isinstance(labels, dict) or not labels
                or any(not isinstance(name, str) or not name or not isinstance(label, str) or label not in REFERENCE_LABELS
                       for name, label in labels.items())):
            raise ValueError("labels.json phải ánh xạ tên ảnh sang aircraft_carrier/not_aircraft_carrier.")
    images = []
    for path in sorted(root.rglob("*")):
        # Do not follow reference links into other folders or omit them silently.
        if path.is_symlink():
            raise ValueError("Reference assets must be files inside the configured folder, not symlinks.")
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError("Reference image is outside the configured folder.")
        data, width, height = normalize_image(_read_bounded(path, MAX_IMAGE_BYTES))
        name = path.relative_to(root).as_posix()
        if labels is not None and name not in labels:
            raise ValueError("labels.json thiếu nhãn cho ảnh mẫu: " + name)
        images.append(ReferenceImage(reference_id(name, data), name, data, width, height,
                                     label=labels[name] if labels is not None else "aircraft_carrier"))
    if not images:
        raise ValueError("Folder tham chiếu chưa có ảnh mẫu tàu sân bay.")
    if labels is not None and set(labels) != {image.name for image in images}:
        raise ValueError("labels.json có tên ảnh không tồn tại trong bộ mẫu.")
    images = tuple(images)
    return ReferenceLibrary(description, images, library_revision(description, images))
