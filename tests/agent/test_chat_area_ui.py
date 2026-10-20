"""Run the actual chat-area browser controller without live services."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_chat_area_draw_confirm_clear_restore_and_conflict():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required for the drawing probe")
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run([
        node, str(Path(__file__).with_name("chat_area_controls_probe.cjs")),
        str(root / "ship_agent/map_assets/chat_area_controls.js"),
    ], check=True, capture_output=True, text=True, timeout=15)
    assert "probe passed" in completed.stdout
