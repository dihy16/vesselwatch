"""Render known chat image links through display previews, never model pixel inputs."""

import re
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from file_server.media.image_assets import image_preview_url


_IMAGE = re.compile(r'!\[(?P<alt>[^\]\n]*)\]\((?:<(?P<angle>[^>\n]+)>|(?P<url>[^\s)]+))\)')
_CODE = re.compile(r'(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)')


def has_image_results(results):
    if isinstance(results, list):
        return any(has_image_results(item) for item in results)
    if isinstance(results, dict):
        return any(key in {"images", "reference_images", "image_url"} and bool(value)
                   or has_image_results(value) for key, value in results.items())
    return False


def render_chat_image_previews(text, observations, results, *, data_source="file_server"):
    """Only inline Markdown for registered targets/current references is rewritten."""
    links = {}

    def add(url, width=None, height=None, *, original_url=None):
        if not isinstance(url, str) or any(char.isspace() or char in '<>()' for char in url):
            return
        try:
            preview = image_preview_url(url)
        except ValueError:
            return
        original = original_url or links.get(url, {}).get("original", url)
        info = {"original": original, "preview": preview}
        if all(type(value) is int and value > 0 for value in (width, height)):
            info["dimensions"] = (width, height)
        links[url] = links[original] = links[preview] = info

    for row in observations:
        for image in row.get("images", []):
            url, identity = image.get("url"), image.get("image_id")
            if (isinstance(url, str) and isinstance(identity, str)
                    and unquote(urlsplit(url).path).endswith("/images/" + identity)):
                original = url
                if data_source == "demo":
                    parts = urlsplit(url)
                    query = [(key, value) for key, value in parse_qsl(parts.query) if key not in {"original", "preview"}]
                    original = urlunsplit(parts._replace(query=urlencode([*query, ("original", "1")])))
                add(url, original_url=original)

    def visit(value, revision=None):
        if isinstance(value, list):
            for item in value:
                visit(item, revision)
        elif isinstance(value, dict):
            revision = value.get("reference_revision", revision)
            url = value.get("image_url")
            if isinstance(url, str) and url in links:
                add(url, value.get("image_width_px"), value.get("image_height_px"))
            identity, url = value.get("reference_id"), value.get("url")
            if (isinstance(identity, str) and re.fullmatch(r"[a-f0-9]{32}", identity)
                    and isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{64}", revision)
                    and isinstance(url, str)):
                parts = urlsplit(url)
                if (parts.path.endswith("/carrier-references/images/" + identity)
                        and parse_qs(parts.query).get("revision") == [revision]):
                    add(url, value.get("width"), value.get("height"))
            for item in value.values():
                if isinstance(item, (list, dict)):
                    visit(item, revision)

    visit(results)

    def replace_images(section):
        def replace(match):
            url = match.group("angle") or match.group("url")
            info = links.get(url)
            if info is None:
                return match.group(0)
            image = f'![{match.group("alt")}]({info["preview"]})'
            already_linked = (match.start() > 0 and section[match.start() - 1] == "["
                              and section[match.end():].startswith("]("))
            if already_linked:
                return image
            caption = ""
            if "dimensions" in info:
                width, height = info["dimensions"]
                caption = f" (ảnh gốc {width}×{height} px)"
            return f'[{image}]({info["original"]})' + caption
        return _IMAGE.sub(replace, section)

    sections = _CODE.split(text)
    return "".join(section if index % 2 else replace_images(section)
                   for index, section in enumerate(sections))
