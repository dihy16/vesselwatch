"""Independent pixel-size, aspect-ratio and source-integrity checks for variants."""

from hashlib import sha256
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

from PIL import Image
import pytest

from file_server.media.carrier_references import load_reference_library
from file_server.media.image_assets import (
    image_preview_url, normalize_image, prepare_preview_image, prepare_vision_image,
)
from tests.file_server.test_carrier_references import png, reference_folder


@pytest.mark.parametrize("source,vision,preview", [
    ((48, 26), (224, 121), (384, 208)),
    ((26, 48), (121, 224), (208, 384)),
    ((32, 32), (224, 224), (384, 384)),
    ((224, 100), (224, 100), (384, 171)),
    ((1024, 512), (1024, 512), (384, 192)),
    ((1, 48), (5, 224), (8, 384)),
])
def test_original_normalization_vision_and_preview_have_distinct_dimensions(source, vision, preview):
    original = png("green", source)
    before = sha256(original).hexdigest()
    normalized, width, height = normalize_image(original)
    assert (width, height) == source and normalized == original
    sent, shown = prepare_vision_image(original), prepare_preview_image(original)
    for variant, expected in ((sent, vision), (shown, preview)):
        with Image.open(BytesIO(variant.data)) as decoded:
            assert decoded.size == expected and decoded.mode == "RGB" and decoded.format == "PNG"
            assert decoded.getpixel((expected[0] // 2, expected[1] // 2)) == (0, 128, 0)
        assert (variant.original_width, variant.original_height) == source
    assert sha256(original).hexdigest() == before
    assert sent.metadata()["image_width_px"] == source[0]
    assert sent.metadata()["vision_image_width_px"] == vision[0]
    assert sent.metadata()["image_resampling"] == ("none" if source == vision else "bilinear")


def test_bilinear_resampling_is_bounded_interpolation_not_generated_detail():
    image = Image.new("RGB", (2, 1), "black")
    image.putpixel((1, 0), (255, 255, 255))
    out = BytesIO()
    image.save(out, format="PNG")
    variant = prepare_vision_image(out.getvalue())
    with Image.open(BytesIO(variant.data)) as resized:
        assert resized.size == (224, 112)
        assert resized.getpixel((0, 56)) == (0, 0, 0)
        assert resized.getpixel((223, 56)) == (255, 255, 255)
        red, green, blue = resized.getpixel((112, 56))
        assert red == green == blue and 0 < red < 255


def test_variant_generation_preserves_manifest_identity_and_reference_files(tmp_path):
    library = load_reference_library(reference_folder(tmp_path))
    source = (tmp_path / "known.png").read_bytes()
    manifest = library.manifest("http://public:8001")
    for image in library.images:
        prepare_vision_image(image.data)
        prepare_preview_image(image.data)
    assert (tmp_path / "known.png").read_bytes() == source
    assert load_reference_library(tmp_path) == library
    assert library.manifest("http://public:8001") == manifest
    record = manifest["images"][0]
    assert record["width"] == 32 and record["height"] == 24
    assert parse_qs(urlsplit(record["preview_url"]).query) == {"revision": [library.revision], "preview": ["1"]}


@pytest.mark.parametrize("data", [b"", b"invalid-image"])
def test_invalid_images_do_not_produce_preview_or_vision_pixels(data):
    for prepare in (prepare_preview_image, prepare_vision_image):
        with pytest.raises((OSError, ValueError)):
            prepare(data)


def test_original_limits_are_checked_before_resize_and_output_limits_after_resize():
    original = png(size=(48, 26))
    with pytest.raises(ValueError):
        prepare_vision_image(original, max_bytes=len(original) - 1)
    with pytest.raises(ValueError):
        prepare_vision_image(original, max_pixels=100)
    with pytest.raises(ValueError):
        prepare_vision_image(original, max_pixels=2000)  # Original fits, output does not.


def test_preview_query_preserves_revision_and_never_conflicts_with_original_mode():
    url = "http://public:8001/images/id?revision=abc&original=true&preview=0"
    actual = image_preview_url(url)
    assert parse_qs(urlsplit(actual).query) == {"revision": ["abc"], "preview": ["1"]}
    assert image_preview_url(actual) == actual
    with pytest.raises(ValueError):
        image_preview_url("file:///private/image.png")
