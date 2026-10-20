"""JSON persistence, chat isolation, validation and HTTP selection lifecycle."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import httpx
import pytest

from file_server.chat_areas import AreaConflict, ChatAreaStore
from scripts.run_vessel_map_demo import inject_chat_controls, make_session_handler

SQUARE = {"type": "Polygon", "coordinates": [[[110, 15], [112, 15], [112, 17], [110, 17], [110, 15]]]}


def test_save_overwrite_clear_and_restart_are_isolated(tmp_path):
    store = ChatAreaStore(tmp_path)
    first = store.ensure("user", "chat-1")
    other_chat = store.ensure("user", "chat-2")
    other_user = store.ensure("other", "chat-1")
    saved = store.set_area(first["session_id"], SQUARE, 0)
    assert saved["active_area"] == SQUARE and saved["revision"] == 1
    assert store.ensure("user", "chat-1")["session_id"] == first["session_id"]
    restarted = ChatAreaStore(tmp_path)
    assert restarted.get(first["session_id"])["active_area"] == SQUARE
    changed = restarted.set_area(first["session_id"], {"type": "preset", "key": "vinh_bac_bo"}, 1)
    assert changed["active_area"]["key"] == "vinh_bac_bo"
    assert store.get(other_chat["session_id"])["active_area"] is None
    assert store.get(other_user["session_id"])["active_area"] is None
    assert restarted.set_area(first["session_id"], None, 2)["active_area"] is None
    assert len(list(tmp_path.glob("*.json"))) == 3
    assert not list(tmp_path.glob("tmp*"))


def test_failed_selection_keeps_confirmed_area(tmp_path):
    store = ChatAreaStore(tmp_path)
    saved = store.ensure("u", "c")
    token = saved["session_id"]
    store.set_area(token, SQUARE, 0)
    invalid = {"type": "Polygon", "coordinates": [[[110, 15], [112, 17], [110, 17], [112, 15], [110, 15]]]}
    for area in (invalid, {"type": "preset", "key": "hoang_sa"},
                 {"type": "preset", "key": []}, [SQUARE, SQUARE]):
        with pytest.raises(ValueError):
            store.set_area(token, area, 1)
        assert store.get(token)["active_area"] == SQUARE
    with pytest.raises(KeyError):
        store.get("../outside")
    with pytest.raises(AreaConflict):
        store.set_area(token, None, 0)
    assert store.get(token)["revision"] == 1


def test_two_windows_cannot_silently_overwrite_same_revision(tmp_path):
    store = ChatAreaStore(tmp_path)
    token = store.ensure("u", "c")["session_id"]
    def save():
        try:
            store.set_area(token, SQUARE, 0)
            return "saved"
        except AreaConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: save(), range(2))) == ["conflict", "saved"]
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["revision"] == 1


@pytest.fixture
def session_server(tmp_path):
    class BaseHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"original map")
        def log_message(self, *args):
            pass
    store = ChatAreaStore(tmp_path)
    with ThreadingHTTPServer(("127.0.0.1", 0), make_session_handler(BaseHandler, store)) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", store
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_session_api_lifecycle_and_original_routes(session_server):
    base, _ = session_server
    with httpx.Client(base_url=base, trust_env=False) as client:
        assert client.get("/demo/vessel_map.html").text == "original map"
        saved = client.post("/map-sessions", json={"user_id": "u", "chat_id": "c"}).json()
        path = f"/map-sessions/{saved['session_id']}"
        assert client.get(path).json()["active_area"] is None
        result = client.put(path + "/area", json={"active_area": SQUARE, "expected_revision": 0})
        assert result.status_code == 200 and result.json()["revision"] == 1
        assert client.put(path + "/area", json={"active_area": None, "expected_revision": 0}).status_code == 409
        assert client.put(path + "/area", json={"active_area": None, "expected_revision": 1}).json()["active_area"] is None
        assert client.post("/map-sessions", json={"user_id": "u", "chat_id": "c", "extra": 1}).status_code == 422
        assert client.get("/map-sessions/" + "0" * 64).status_code == 404


def test_template_injection_does_not_replace_existing_map():
    html = '<script>const map = existingMap;\n      const tiles = L.tileLayer("tiles");</script>'
    result = inject_chat_controls(html)
    assert 'const map = existingMap;' in result
    assert result.count('ChatAreaControls.attach({ map, L, document });') == 1
    assert result.index('ChatAreaControls.attach') < result.index('const tiles =')
    with pytest.raises(ValueError):
        inject_chat_controls('<html>unsupported demo</html>')
