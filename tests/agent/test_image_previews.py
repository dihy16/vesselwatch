"""Chat rendering uses registered previews without changing model/source URLs."""

from copy import deepcopy

from ship_agent.artifacts.image_previews import has_image_results, render_chat_image_previews


RAW = "http://public:8001/images/id"
PREVIEW = RAW + "?preview=1"
ROWS = [{"observation_id": "one", "images": [{"image_id": "id", "url": RAW}]}]


def test_target_preview_is_enlarged_clickable_to_original_and_keeps_native_dimensions():
    result = {"image_url": RAW, "image_width_px": 48, "image_height_px": 26,
              "vision_image_width_px": 224, "vision_image_height_px": 121}
    before = deepcopy((ROWS, result))
    rendered = render_chat_image_previews(f"![Tàu]({RAW})", ROWS, [result])
    assert rendered == f"[![Tàu]({PREVIEW})]({RAW}) (ảnh gốc 48×26 px)"
    assert (ROWS, result) == before
    assert render_chat_image_previews(rendered, ROWS, [result]) == rendered


def test_reference_preview_uses_current_manifest_identity_and_preserves_revision():
    identity, revision = "a" * 32, "b" * 64
    url = f"http://public/ carrier-references/images/{identity}?revision={revision}".replace("/ ", "/")
    result = {"reference_revision": revision, "reference_images": [{
        "reference_id": identity, "name": "ref1.png", "url": url, "width": 200, "height": 150}]}
    actual = render_chat_image_previews(f"![ref1]({url})", [], [result])
    assert f"{url}&preview=1" in actual and f"]({url})" in actual
    assert "200×150" in actual
    result["reference_revision"] = "c" * 64
    assert render_chat_image_previews(f"![ref1]({url})", [], [result]) == f"![ref1]({url})"


def test_search_images_work_without_review_and_unknown_urls_charts_and_code_are_unchanged():
    text = f"![Tàu]({RAW}) ![Unknown](http://elsewhere/image) ![Chart](http://public/charts/a.png)"
    actual = render_chat_image_previews(text, ROWS, [])
    assert PREVIEW in actual and "ảnh gốc" not in actual
    assert "![Unknown](http://elsewhere/image)" in actual and "![Chart](http://public/charts/a.png)" in actual
    code = f"```html\n<img src='{RAW}'>\n![example]({RAW})\n``` `![inline]({RAW})`"
    assert render_chat_image_previews(code, ROWS, []) == code


def test_demo_preview_clicks_through_to_actual_original_not_legacy_preview():
    actual = render_chat_image_previews(f"![Tàu]({RAW})", ROWS, [], data_source="demo")
    assert actual == f"[![Tàu]({PREVIEW})]({RAW}?original=1)"


def test_existing_image_link_is_preserved_without_nested_links():
    text = f"[![Tàu]({RAW})]({RAW})"
    assert render_chat_image_previews(text, ROWS, []) == f"[![Tàu]({PREVIEW})]({RAW})"


def test_only_image_results_need_delayed_final_rendering():
    assert has_image_results([{"ships": ROWS}])
    assert has_image_results([{"flags": [{"image_url": RAW}]}])
    assert not has_image_results([{"total": 0, "ships": []}])
    assert not has_image_results([{"daily_stats": [{"count": 3}]}])
