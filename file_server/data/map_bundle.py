"""Load the hosted map's own runtime and saved predictions without copying data."""

from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path
import sys
from types import ModuleType


def bundle_modules(bundle: Path):
    directory = bundle.resolve() / "demo"
    if not (directory / "vessel_demo_api.py").is_file():
        raise ValueError(f"Missing exported map runtime: {directory}")
    # A private namespace avoids collisions with another project's `demo` package.
    name = "_vessel_map_" + sha256(str(directory).encode()).hexdigest()[:16]
    if name not in sys.modules:
        package = ModuleType(name)
        package.__path__ = [str(directory)]
        package.__package__ = name
        sys.modules[name] = package
    return tuple(import_module(name + "." + module) for module in
                 ("demo_config", "vessel_demo_api", "pack_vessel_map"))


def load_bundle(bundle: Path):
    config, api, _ = bundle_modules(bundle)
    local_config = bundle.resolve() / "demo/local_config.json"
    if not local_config.is_file():
        raise ValueError(f"Missing map dataset configuration: {local_config}")
    manifest = config.configured_manifest(local_config)
    run, seed = config.configured_saved_run(local_config)
    if run is None:
        raise ValueError(f"Set saved_run_dir in {local_config} before querying saved predictions.")
    data = api.VesselDemoStore(manifest, "", saved_run_dir=run, saved_run_seed=seed)
    fingerprint = sha256(json.dumps(data.sources, sort_keys=True, ensure_ascii=True,
                                   allow_nan=False).encode()).hexdigest()
    return data, {"data_source": "map_bundle", "manifest": str(manifest),
                  "saved_run_dir": str(run), "runs": [run.name], "saved_run_seed": seed,
                  "map_snapshot_id": fingerprint}
