"""Reference snapshots include every valid image and never invent example assets."""

from io import BytesIO
import json

from PIL import Image
import pytest

from file_server.media.carrier_references import load_reference_library
from file_server.media.image_assets import normalize_image


def png(color="blue", size=(32, 24)):
    out = BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def reference_folder(tmp_path):
    (tmp_path / "description.md").write_text("Đối chiếu hình dạng boong và cấu trúc nhìn thấy.", encoding="utf-8")
    (tmp_path / "known.png").write_bytes(png())
    return tmp_path


def test_all_images_including_subfolders_have_stable_pixel_bound_ids(tmp_path):
    folder = reference_folder(tmp_path)
    (folder / "more").mkdir()
    (folder / "more/second.png").write_bytes(png("red"))
    library = load_reference_library(folder)
    assert [image.name for image in library.images] == ["known.png", "more/second.png"]
    assert load_reference_library(folder) == library
    assert len({image.reference_id for image in library.images}) == 2
    manifest = library.manifest("http://viewer:8001")
    assert all("revision=" + library.revision in image["url"] for image in manifest["images"])
    (folder / "known.png").write_bytes(png("green"))
    changed = load_reference_library(folder)
    assert changed.revision != library.revision
    assert changed.images[0].reference_id != library.images[0].reference_id
    assert library.images[0].data != changed.images[0].data  # Prior snapshot stays immutable.


@pytest.mark.parametrize("state", ["missing-description", "empty-description", "missing-images", "corrupt-image"])
def test_incomplete_libraries_fail_instead_of_dropping_references(tmp_path, state):
    reference_folder(tmp_path)
    if state == "missing-description":
        (tmp_path / "description.md").unlink()
    elif state == "empty-description":
        (tmp_path / "description.md").write_text("")
    elif state == "missing-images":
        (tmp_path / "known.png").unlink()
    else:
        (tmp_path / "another.png").write_bytes(b"bad pixels")
    with pytest.raises((ValueError, OSError)):
        load_reference_library(tmp_path)


def test_changing_only_description_changes_revision(tmp_path):
    folder = reference_folder(tmp_path)
    before = load_reference_library(folder)
    (folder / "description.md").write_text("Mô tả khác", encoding="utf-8")
    after = load_reference_library(folder)
    assert before.revision != after.revision
    assert before.images == after.images


def test_label_changes_revision_but_preserves_image_identity_and_pixels(tmp_path):
    folder = reference_folder(tmp_path)
    original = load_reference_library(folder)
    (folder / "labels.json").write_text(json.dumps({"known.png": "not_aircraft_carrier"}))
    changed = load_reference_library(folder)
    assert original.revision != changed.revision
    assert original.images[0].reference_id == changed.images[0].reference_id
    assert original.images[0].data == changed.images[0].data
    assert changed.manifest("http://viewer")["images"][0]["label"] == "not_aircraft_carrier"


@pytest.mark.parametrize("labels", [{}, {"other.png": "aircraft_carrier"},
    {"known.png": "unknown"}, {"known.png": []},
    {"known.png": "aircraft_carrier", "missing.png": "not_aircraft_carrier"}])
def test_label_manifest_must_cover_exactly_every_image_with_valid_labels(tmp_path, labels):
    reference_folder(tmp_path)
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    with pytest.raises(ValueError):
        load_reference_library(tmp_path)


def test_limits_apply_to_raw_and_decoded_images():
    with pytest.raises(ValueError):
        normalize_image(png(), max_bytes=10)
    with pytest.raises(ValueError):
        normalize_image(png(), max_pixels=100)


def test_symlink_reference_not_silently_followed_or_omitted(tmp_path):
    folder = reference_folder(tmp_path)
    try:
        (folder / "linked.png").symlink_to(folder / "known.png")
    except OSError:
        pytest.skip("Creating symlinks requires privileges on this host")
    with pytest.raises(ValueError, match="symlinks"):
        load_reference_library(folder)
