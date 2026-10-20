"""Run the exported 5,230-observation map with chat-linked polygon storage."""

import argparse
import gzip
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from file_server.chat_areas import AreaConflict, ChatAreaStore
from file_server.spatial import AREA_NAMES, predefined_geometry
from file_server.map_bundle import bundle_modules, load_bundle


def inject_chat_controls(html):
    marker = '      const tiles = L.tileLayer('
    if html.count(marker) != 1:
        raise ValueError("Demo template changed: cannot attach chat polygon controls safely.")
    script = (ROOT / "ship_agent/map_assets/chat_area_controls.js").read_text(encoding="utf-8")
    return html.replace(marker, script + "\n      ChatAreaControls.attach({ map, L, document });\n" + marker)


def make_session_handler(base_handler, store, dataset_info=None):
    """Extend the original local demo handler without changing its exported files."""
    class Handler(base_handler):
        def _send_json(self, status, data):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            compressed = len(body) > 65536 and "gzip" in self.headers.get("Accept-Encoding", "")
            if compressed:
                body = gzip.compress(body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if compressed:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self.end_headers()
            self.wfile.write(body)

        def _body(self, keys):
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("Content-Length không hợp lệ.") from exc
            if not 0 < size <= 65536:
                raise ValueError("JSON cần có nội dung và không vượt quá 64 KiB.")
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict) or set(value) != set(keys):
                raise ValueError("Các trường JSON không hợp lệ.")
            return value

        def _handle_session(self):
            path = urlsplit(self.path).path
            try:
                if self.command == "POST" and path == "/map-sessions":
                    data = self._body({"user_id", "chat_id"})
                    self._send_json(200, store.ensure(**data))
                elif self.command == "GET" and re.fullmatch(r"/map-sessions/[a-f0-9]{64}", path):
                    self._send_json(200, store.get(path.rsplit("/", 1)[1]))
                elif self.command == "PUT" and re.fullmatch(r"/map-sessions/[a-f0-9]{64}/area", path):
                    data = self._body({"active_area", "expected_revision"})
                    self._send_json(200, store.set_area(path.split("/")[2], **data))
                elif self.command == "GET" and path.startswith("/query-areas/"):
                    key = path.rsplit("/", 1)[1]
                    if key not in AREA_NAMES:
                        raise KeyError("Khu vực này cần người dùng tự vẽ.")
                    self._send_json(200, {"type": "Feature", "properties": {"name": AREA_NAMES[key]},
                                          "geometry": predefined_geometry(key).geometry})
                else:
                    self._send_json(404, {"detail": "Không tìm thấy API vùng."})
            except AreaConflict as exc:
                self._send_json(409, {"detail": str(exc)})
            except KeyError:
                self._send_json(404, {"detail": "Không tìm thấy phiên map hoặc khu vực."})
            except (ValueError, UnicodeDecodeError) as exc:
                self._send_json(422, {"detail": str(exc)})
            except OSError:
                self._send_json(500, {"detail": "Chưa đọc/ghi được file vùng chat."})

        def do_GET(self):
            if urlsplit(self.path).path == "/dataset-info" and dataset_info is not None:
                self._send_json(200, dataset_info)
                return
            if urlsplit(self.path).path.startswith(("/map-sessions", "/query-areas/")):
                self._handle_session()
            else:
                super().do_GET()

        def do_POST(self):
            self._handle_session()

        def do_PUT(self):
            self._handle_session()

        def log_message(self, format, *args):
            # A map-session URL grants access to its selection; don't log its token.
            if "/map-sessions/" in self.path or "map_session=" in self.path:
                return
            super().log_message(format, *args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo-dir", type=Path, default=ROOT / "data/exports/vessel-map-demo")
    parser.add_argument("--session-dir", type=Path, default=ROOT / "data/map_sessions")
    args = parser.parse_args()
    bundle = args.demo_dir.expanduser().resolve()
    if not (bundle / "demo/vessel_demo_api.py").is_file():
        parser.error(f"Missing exported demo at {bundle}; set --demo-dir to the extracted bundle root.")
    config, api, packer = bundle_modules(bundle)
    data, provenance = load_bundle(bundle)
    html = packer.build_html(data.manifest_path, classifier_base_url=config.configured_classifier_base_url(
        bundle / "demo/local_config.json"))
    data.html = inject_chat_controls(html).encode("utf-8")
    handler = make_session_handler(api.make_handler(data), ChatAreaStore(args.session_dir),
                                   {**provenance, "observation_count": len(data.sources)})
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Vessel map: http://127.0.0.1:{server.server_port}/demo/vessel_map.html", flush=True)
        print(f"Observations: {len(data.sources)}; chat-area JSON: {args.session_dir.resolve()}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
