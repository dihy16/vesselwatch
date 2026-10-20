"""Immutable reference-library snapshots loaded from the configured local folder."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from .image_assets import MAX_IMAGE_BYTES, normalize_image

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
MAX_DESCRIPTION_BYTES = 65536


@dataclass(frozen=True)
class ReferenceImage:
    reference_id: str
    name: str
    data: bytes
    width: int
    height: int


def reference_id(name: str, data: bytes) -> str:
    return sha256(name.encode("utf-8") + b"\0" + data).hexdigest()[:32]


def library_revision(description: str, images) -> str:
    return sha256(json.dumps({"description": description,
        "images": sorted((image.name, image.reference_id) for image in images)},
        ensure_ascii=True, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ReferenceLibrary:
    description: str
    images: tuple[ReferenceImage, ...]
    revision: str

    def manifest(self, base_url: str):
        return {"description": self.description, "revision": self.revision,
                "images": [{"reference_id": image.reference_id, "name": image.name,
                            "width": image.width, "height": image.height, "mime_type": "image/png",
                            "url": base_url.rstrip("/") + f"/carrier-references/images/{image.reference_id}?revision={self.revision}"}
                           for image in self.images]}


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
        images.append(ReferenceImage(reference_id(name, data), name, data, width, height))
    if not images:
        raise ValueError("Folder tham chiếu chưa có ảnh mẫu tàu sân bay.")
    images = tuple(images)
    return ReferenceLibrary(description, images, library_revision(description, images))
