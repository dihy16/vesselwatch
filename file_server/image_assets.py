"""Decode bounded local image assets into vision-compatible PNG pixels."""

from io import BytesIO
import warnings

from PIL import Image

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000


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
