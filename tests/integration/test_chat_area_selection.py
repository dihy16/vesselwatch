"""Agent selection uses the existing map API, identities and optimistic revision lock."""

from copy import deepcopy
import json

import httpx
from pydantic import ValidationError
import pytest

from file_server.schemas.area_models import AreaQueryInput
from file_server.storage.chat_areas import AreaConflict, ChatAreaStore
from ship_agent.clients.chat_area_client import save_chat_area, selection_area
from ship_agent.runtime.chat_area import apply_chat_area
from ship_agent.tools.schemas import ChatAreaQueryInput, ObservationAnalysisInput
from tests.file_server.test_chat_areas import SQUARE
from tests.file_server import test_chat_areas as chat_area_fixtures

session_server = chat_area_fixtures.session_server


def test_select_square_save_then_follow_up_uses_fresh_session_without_pipe_changes(session_server, monkeypatch):
    import ship_agent.config as config
    base, store = session_server
    monkeypatch.setattr(config, "MAP_API_URL", base)
    context = store.ensure("user", "chat")
    original = deepcopy(context)
    area = selection_area(AreaQueryInput(area_name="Du Lâm", radius_nm=20))
    selected = save_chat_area(context, area)
    assert context == original and context["active_area"] is None
    assert selected["active_area"] == area and selected["revision"] == 1
    assert context["session_id"] not in json.dumps(selected)
    fresh = store.ensure("user", "chat")
    runtime = {"configurable": {"thread_id": "chat", "chat_area_context": fresh}}
    assert apply_chat_area({}, runtime)["polygon"] == area
    assert store.ensure("user", "other-chat")["active_area"] is None
    with pytest.raises(ValueError):
        save_chat_area(context, SQUARE)  # An in-flight old snapshot cannot overwrite the new area.
    assert store.get(context["session_id"])["active_area"] == area


@pytest.mark.parametrize("area", [{"type": "preset", "key": "bien_dong"}, SQUARE])
def test_only_trusted_api_is_used_and_session_credentials_stay_private(tmp_path, monkeypatch, area):
    import ship_agent.config as config
    monkeypatch.setattr(config, "MAP_API_URL", "http://trusted/prefix")
    store = ChatAreaStore(tmp_path)
    context = store.ensure("u", "c")
    context["map_url"] = "http://untrusted/map"
    requests = []
    def respond(request):
        requests.append(request)
        assert str(request.url).startswith("http://trusted/prefix/map-sessions/")
        if request.method == "GET":
            return httpx.Response(200, json=store.get(context["session_id"]))
        body = json.loads(request.content)
        return httpx.Response(200, json=store.set_area(context["session_id"], body["active_area"], body["expected_revision"]))
    result = save_chat_area(context, area, transport=httpx.MockTransport(respond))
    assert [r.method for r in requests] == ["GET", "PUT"]
    assert result["active_area"] == area and "session_id" not in result


@pytest.mark.parametrize("change", ["foreign-user", "foreign-chat", "missing-session", "invalid-revision"])
def test_invalid_or_foreign_context_never_writes(session_server, monkeypatch, change):
    import ship_agent.config as config
    base, store = session_server
    monkeypatch.setattr(config, "MAP_API_URL", base)
    context = store.ensure("u", "c")
    token = context["session_id"]
    if change == "foreign-user":
        context["user_id"] = "other"
    elif change == "foreign-chat":
        context["chat_id"] = "other"
    elif change == "missing-session":
        context.pop("session_id")
    else:
        context["revision"] = True
    with pytest.raises(ValueError):
        save_chat_area(context, SQUARE)
    assert store.get(token)["revision"] == 0


def test_edit_between_read_and_write_is_not_retried_or_overwritten(tmp_path):
    store = ChatAreaStore(tmp_path)
    context = store.ensure("u", "c")
    calls = []
    def respond(request):
        calls.append(request.method)
        if request.method == "GET":
            previous = store.get(context["session_id"])
            store.set_area(context["session_id"], {"type": "preset", "key": "vinh_bac_bo"}, 0)
            return httpx.Response(200, json=previous)
        body = json.loads(request.content)
        with pytest.raises(AreaConflict):
            store.set_area(context["session_id"], body["active_area"], body["expected_revision"])
        return httpx.Response(409)
    with pytest.raises(httpx.HTTPStatusError):
        save_chat_area(context, SQUARE, transport=httpx.MockTransport(respond))
    assert calls == ["GET", "PUT"]
    assert store.get(context["session_id"])["active_area"] == {"type": "preset", "key": "vinh_bac_bo"}


def test_selection_is_explicit_and_is_not_advertised_on_analysis_tool():
    assert not ChatAreaQueryInput().set_as_chat_area
    assert "set_as_chat_area" not in ObservationAnalysisInput.model_fields
    with pytest.raises(ValidationError):
        ChatAreaQueryInput(use_chat_area=True, set_as_chat_area=True)
    for values in ({}, {"area_name": "Hoàng Sa"}, {"area_id": "a" * 32}):
        with pytest.raises(ValueError):
            selection_area(AreaQueryInput(**values))
    assert selection_area(AreaQueryInput(area_name="Vịnh Bắc Bộ")) == {"type": "preset", "key": "vinh_bac_bo"}
