"""Regression coverage for package imports, resources and supported entry points."""

import ast
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_local_imports_reference_existing_modules_and_definitions():
    """Catch dangling imports even when optional service dependencies are unavailable."""
    exports = {}
    for package in ("file_server", "ship_agent"):
        for path in (ROOT / package).rglob("*.py"):
            module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
            if module.endswith(".__init__"):
                module = module.removesuffix(".__init__")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = set()
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    names.update(child.id for child in ast.walk(node)
                                 if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store))
            exports[module] = names
    exports["ship_agent.tools"].add("create_tools")  # Lazy public export.
    errors = []
    for package in ("file_server", "ship_agent", "scripts", "tests"):
        for path in (ROOT / package).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith(("file_server", "ship_agent")):
                    continue
                if node.module not in exports:
                    errors.append(f"{path.name}:{node.lineno}: {node.module}")
                    continue
                for alias in node.names:
                    if alias.name not in exports[node.module] and f"{node.module}.{alias.name}" not in exports:
                        errors.append(f"{path.name}:{node.lineno}: {node.module}.{alias.name}")
    assert errors == []


def test_contracts_clients_and_packages_import_without_frameworks_network_or_snapshots():
    code = """
import importlib
import httpx
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('Import must not access network or load a dataset')
httpx.Client.get = httpx.Client.post = forbidden
import file_server.data.loader as loader
loader.load_store = forbidden
for name in (
    'file_server.schemas.observations', 'file_server.schemas.area_models',
    'file_server.schemas.reviews', 'file_server.schemas.monitoring',
    'ship_agent.runtime', 'ship_agent.tools', 'ship_agent.tools.schemas',
    'ship_agent.vision.schemas', 'ship_agent.clients.file_server_client',
    'ship_agent.clients.label_review_client',
):
    importlib.import_module(name)
assert not any(name in sys.modules for name in ('fastapi', 'langgraph', 'langchain_openai'))
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)


def test_resources_resolve_from_nested_modules():
    from file_server.services.spatial import AREA_DATA, predefined_geometry
    from ship_agent.artifacts.map_artifacts import ASSETS, render_map
    from ship_agent.data.demo_data import PROJECT_ROOT

    assert AREA_DATA == ROOT / "file_server/area_data"
    assert ASSETS == ROOT / "ship_agent/map_assets" and PROJECT_ROOT == ROOT
    assert predefined_geometry("vinh_bac_bo").geometry["type"] in {"Polygon", "MultiPolygon"}
    page = render_map({"filters": {"observed_from": "2025-01-01", "observed_to": "2025-12-31"}, "vessels": []})
    assert "__LEAFLET_JS__" not in page and "__LEAFLET_CSS__" not in page
    assert "leaflet" in page.lower()


def test_area_record_storage_has_no_http_dependency_and_keeps_json_format(tmp_path):
    from file_server.storage.area_records import AreaNotFound, _read, _write

    record = {"status": "complete", "area_name": "Vùng tùy ý", "snapshot_id": "a" * 64,
              "query": {}, "polygon": None, "named_area": None}
    identifier = _write(tmp_path, record)
    assert len(identifier) == 32 and _read(tmp_path, identifier) == record
    assert [path.name for path in tmp_path.iterdir()] == [identifier + ".json"]
    for missing in ("../outside", "f" * 32):
        with pytest.raises(AreaNotFound):
            _read(tmp_path, missing)


def test_supported_agent_entry_points_and_public_tool_export():
    pytest.importorskip("langchain_core")
    pytest.importorskip("langchain_openai")
    pytest.importorskip("langgraph")
    from ship_agent.agent import build_agent
    from ship_agent.runtime.agent import build_agent as runtime_builder
    from ship_agent.tools import create_tools
    from ship_agent.tools.registry import create_tools as registry

    assert build_agent is runtime_builder and create_tools is registry
    result = subprocess.run([sys.executable, "-m", "ship_agent", "--mock-tools", "--today", "2026-10-13"],
                            cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
    assert '"count_ships"' in result.stdout
    result = subprocess.run([sys.executable, "-m", "ship_agent.image_review", "--help"],
                            cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
    assert "--observation-id" in result.stdout


def test_supported_app_entry_point_registers_all_routes_without_reading_data(monkeypatch):
    pytest.importorskip("fastapi")
    from file_server.app import create_app
    import file_server.app as app_module

    def forbidden(*args, **kwargs):
        raise AssertionError("Only lifespan loads data")
    monkeypatch.setattr(app_module, "load_store", forbidden)
    paths = {route.path for route in create_app().routes}
    assert paths >= {
        "/health", "/observations", "/ships/{ship_id:path}", "/images/{image_id}",
        "/carrier-references", "/carrier-references/images/{reference_id}",
        "/reports/daily-carriers", "/charts/daily-carriers.png", "/query-areas/{key}",
        "/area-queries", "/area-queries/{area_id}", "/area-queries/{area_id}/confirm",
        "/area-queries/{area_id}/answer", "/observation-analyses", "/missed-carrier-candidates",
        "/false-carrier-candidates", "/carrier-investigation-candidates", "/carrier-hotspots",
        "/carrier-hotspot-candidates", "/vessel-monitoring-reports", "/carrier-label-review-candidates",
    }
    # Bound context methods must retain the request schemas, not expose self/providers.
    schema = create_app().openapi()
    operation = schema["paths"]["/area-queries"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/AreaRequest")
