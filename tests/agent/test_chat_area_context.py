"""The confirmed runtime polygon is authoritative; stale chat text is not."""

from copy import deepcopy

import pytest

from ship_agent.runtime.chat_area import apply_chat_area
from ship_agent.runtime.chat_area import chat_area_note
from file_server.schemas.area_models import AreaQueryInput
from file_server.services.spatial import AreaGeometry
from file_server.services.spatial import query_observations
from tests.file_server.test_chat_areas import SQUARE
from tests.file_server.test_spatial import observation


def config(area=SQUARE, **overrides):
    context = {"chat_id": "chat-1", "user_id": "u", "active_area": deepcopy(area),
               "revision": 1, **overrides}
    return {"configurable": {"thread_id": "chat-1", "chat_area_context": context}}


def test_custom_area_reaches_full_source_spatial_query_with_filters():
    query = {"area_name": None, "area_id": None, "length_gt_m": 250}
    payload = apply_chat_area(query, config())
    assert "polygon" not in query
    shape = AreaGeometry(payload.pop("polygon"))
    rows = [observation("inside", x=111, length=300), observation("outside", x=115, length=300),
            observation("short", x=111, length=250)]
    assert [r["observation_id"] for r in query_observations(rows, AreaQueryInput(**payload), shape)] == ["inside"]


@pytest.mark.parametrize("context", [None, config(None), config(error="unavailable"),
                                    {"configurable": {"thread_id": "wrong", "chat_area_context":
                                     config()["configurable"]["chat_area_context"]}}])
def test_missing_cleared_failed_or_foreign_context_never_becomes_global_query(context):
    with pytest.raises(ValueError):
        apply_chat_area({}, context)


def test_preset_is_a_single_saved_boundary_and_explicit_other_area_is_rejected():
    result = apply_chat_area({}, config({"type": "preset", "key": "bien_dong"}))
    assert result == {"area_name": "Biển Đông"}
    with pytest.raises(ValueError):
        apply_chat_area({"area_name": "Vịnh Bắc Bộ"}, config())


def test_model_note_contains_current_status_but_no_coordinates_or_old_area_id():
    note = chat_area_note(config())
    assert "use_chat_area=true" in note and "110" not in note and "coordinates" not in note
    assert "Chưa có vùng" in chat_area_note(config(None))
    assert "lỗi server map" in chat_area_note(config(error="unavailable"))
    assert chat_area_note({}) == ""
