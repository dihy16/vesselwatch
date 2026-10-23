"""Fetch every reference image from the configured backend into one immutable set."""

import re
from urllib.parse import urlencode, urlsplit, parse_qs

import httpx

from file_server.media.carrier_references import (
    MAX_DESCRIPTION_BYTES,
    REFERENCE_LABELS,
    ReferenceImage,
    ReferenceLibrary,
    library_revision,
    reference_id,
)
from file_server.media.image_assets import MAX_IMAGE_BYTES, normalize_image
from ship_agent import config


def load_carrier_references(*, transport=None) -> ReferenceLibrary:
    with httpx.Client(base_url=config.FILE_SERVER_URL.rstrip("/") + "/", timeout=30,
                      trust_env=False, follow_redirects=False, transport=transport) as client:
        response = client.get("carrier-references")
        response.raise_for_status()
        manifest = response.json()
        if not isinstance(manifest, dict):
            raise ValueError("Invalid reference manifest.")
        description, revision, records = (manifest.get(key) for key in ("description", "revision", "images"))
        if (not isinstance(description, str) or not description.strip()
                or len(description.encode("utf-8")) > MAX_DESCRIPTION_BYTES
                or not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision)
                or not isinstance(records, list) or not records):
            raise ValueError("Reference description or images are missing.")
        images, seen = [], set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Invalid reference image record.")
            identity, name = record.get("reference_id"), record.get("name")
            label = record.get("label", "aircraft_carrier")
            if (not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity)
                    or identity in seen or not isinstance(name, str) or not name
                    or not isinstance(label, str) or label not in REFERENCE_LABELS):
                raise ValueError("Invalid or duplicate reference image identity.")
            seen.add(identity)
            # Never follow arbitrary URLs returned as public viewer metadata.
            path = f"carrier-references/images/{identity}?" + urlencode({"revision": revision})
            with client.stream("GET", path) as image_response:
                image_response.raise_for_status()
                data = bytearray()
                for chunk in image_response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise ValueError("Reference image exceeds size limit.")
            data = bytes(data)
            if reference_id(name, data) != identity:
                raise ValueError("Reference bytes do not match the manifest.")
            normalized, width, height = normalize_image(data)
            if width != record.get("width") or height != record.get("height"):
                raise ValueError("Reference dimensions do not match the manifest.")
            public_url = record.get("url", str(client.base_url) + path)
            if not isinstance(public_url, str):
                raise ValueError("Invalid reference viewer URL.")
            parts = urlsplit(public_url)
            if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password
                    or not parts.path.endswith(f"/carrier-references/images/{identity}")
                    or parse_qs(parts.query).get("revision") != [revision]
                    or any(char.isspace() for char in public_url)):
                raise ValueError("Invalid reference viewer URL.")
            images.append(ReferenceImage(identity, name, normalized, width, height, url=public_url, label=label))
    # No reference is silently dropped, even if any individual download fails.
    if library_revision(description, images) != revision:
        raise ValueError("Reference set changed during download.")
    return ReferenceLibrary(description, tuple(images), revision)
