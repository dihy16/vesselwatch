"""Decode bounded local image assets into vision-compatible PNG pixels."""

from dataclasses import dataclass
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import warnings

from PIL import Image


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
VISION_LONG_EDGE = 224
PREVIEW_LONG_EDGE = 384


@dataclass(frozen=True)
class ImageVariant:
    data: bytes
    original_width: int
    original_height: int
    width: int
    height: int

    def metadata(self):
        return {"image_width_px": self.original_width, "image_height_px": self.original_height,
                "vision_image_width_px": self.width, "vision_image_height_px": self.height,
                "image_resampling": "bilinear" if self.resized else "none"}

    @property
    def resized(self):
        return (self.width, self.height) != (self.original_width, self.original_height)

    def description(self):
        return (f"Kích thước gốc {self.original_width} × {self.original_height} px; "
                f"ảnh gửi model {self.width} × {self.height} px. "
                "Phóng ảnh chỉ nội suy pixel, không bổ sung chi tiết hay tăng độ phân giải gốc.")


def normalize_image(data: bytes, *, max_bytes=MAX_IMAGE_BYTES, max_pixels=MAX_IMAGE_PIXELS):
    if not data or len(data) > max_bytes:
        raise ValueError("Image is empty or exceeds the byte limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                if width * height > max_pixels:
                    raise ValueError("Image exceeds the pixel limit.")
                output = BytesIO()
                image.convert("RGB").save(output, format="PNG")
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError("Image exceeds the pixel limit.") from exc
    encoded = output.getvalue()
    if len(encoded) > max_bytes:
        raise ValueError("Normalized image exceeds the byte limit.")
    return encoded, width, height


def _resize_image(data, long_edge, *, upscale_only, max_bytes, max_pixels):
    normalized, width, height = normalize_image(data, max_bytes=max_bytes, max_pixels=max_pixels)
    if upscale_only and max(width, height) >= long_edge:
        return ImageVariant(normalized, width, height, width, height)
    scale = long_edge / max(width, height)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    if size[0] * size[1] > max_pixels:
        raise ValueError("Resized image exceeds the pixel limit.")
    with Image.open(BytesIO(normalized)) as image:
        resized = image.resize(size, Image.Resampling.BILINEAR)
        output = BytesIO()
        resized.save(output, format="PNG")
    encoded = output.getvalue()
    if len(encoded) > max_bytes:
        raise ValueError("Resized image exceeds the byte limit.")
    return ImageVariant(encoded, width, height, *size)


def prepare_vision_image(data: bytes, *, max_bytes=MAX_IMAGE_BYTES, max_pixels=MAX_IMAGE_PIXELS):
    """Enlarge tiny inputs to 224 px; preserve larger inputs and their detail."""
    return _resize_image(data, VISION_LONG_EDGE, upscale_only=True,
                         max_bytes=max_bytes, max_pixels=max_pixels)


def prepare_preview_image(data: bytes):
    """Render a 384 px display copy without writing or changing source bytes."""
    return _resize_image(data, PREVIEW_LONG_EDGE, upscale_only=False,
                         max_bytes=MAX_IMAGE_BYTES, max_pixels=MAX_IMAGE_PIXELS)


def image_preview_url(url: str):
    """Keep revision/other parameters, replacing only presentation parameters."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Image URL must be an HTTP(S) URL.")
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key not in {"preview", "original"}]
    return urlunsplit(parts._replace(query=urlencode([*query, ("preview", "1")])))
