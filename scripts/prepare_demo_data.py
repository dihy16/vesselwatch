"""Freeze selected, verified ShipClassification crops for the recording demo."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# A December carrier and another independently observed carrier.
CARRIER_DIGESTS = (
    "0e99f80c1e95b0cc97a7397cb3aaeda33a66f11ac33dd88325c3a0dce5963696",
    "f30a54085ff423004a52b923112a27c91c29cc8798c4299aad38444081a883fb",
)
FIRST, LAST = "2025-12-24", "2025-12-30"


def write_snapshot(source_repo: Path, output: Path) -> dict:
    """Copy a small snapshot; never modify the source checkout or infer metadata."""
    source_repo, output = source_repo.resolve(), output.resolve()
    config_path = source_repo / "demo/local_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest_path = (config_path.parent / config["manifest"]).resolve()
    run = (config_path.parent / config["saved_run_dir"]).resolve()
    seed = config.get("saved_run_seed", 42)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    image_root = (manifest_path.parent / document["image_root"]).resolve()
    spec = importlib.util.spec_from_file_location(
        "shipclassification_saved_results", source_repo / "demo/saved_run_results.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = document["vessels"]
    module.apply_saved_results(rows, run, seed)
    report = json.loads((run / "offline_cloud_crop_staged/report.json").read_text(encoding="utf-8"))
    threshold = report["threshold"]

    def usable(row):
        metadata = row.get("metadata", {})
        return (row.get("prediction") and row.get("latitude") is not None
                and row.get("longitude") is not None
                and metadata.get("length_m", 0) > 0 and metadata.get("width_m", 0) > 0)

    indexed = {row["metadata"]["crop_sha256"]: row for row in rows if usable(row)}
    selected = []
    for digest in CARRIER_DIGESTS:
        row = indexed[digest]
        if (row["metadata"]["ground_truth_label"] != "Carrier present"
                or row["prediction"]["carrier_score"] < threshold):
            raise ValueError(f"Selected image is not a saved true positive: {digest}")
        selected.append(row)
    # Include the other located December carrier if not already selected.
    december_carriers = sorted(
        (row for row in indexed.values()
         if FIRST <= row["captured_at"][:10] <= LAST
         and row["metadata"]["ground_truth_label"] == "Carrier present"
         and row["prediction"]["carrier_score"] >= threshold),
        key=lambda row: row["id"],
    )
    for row in december_carriers:
        if row not in selected:
            selected.append(row)
    negatives = sorted(
        (row for row in indexed.values()
         if FIRST <= row["captured_at"][:10] <= LAST
         and row["metadata"]["ground_truth_label"] == "Carrier absent"
         and row["prediction"]["carrier_score"] < threshold),
        key=lambda row: (row["captured_at"], row["id"]),
    )
    # Round-robin days rather than taking eight records from a single acquisition.
    day_groups = {}
    for row in negatives:
        day_groups.setdefault(row["captured_at"][:10], []).append(row)
    target_count = len(selected) + 8
    while len(selected) < target_count:
        added = False
        for group in day_groups.values():
            if group:
                selected.append(group.pop(0))
                added = True
                if len(selected) >= target_count:
                    break
        if not added:
            break

    prepared = []
    ship_ids = set()
    for index, row in enumerate(selected, 1):
        path = (image_root / row["image_path"]).resolve()
        if not path.is_relative_to(image_root) or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("Demo images must be registered PNG/JPEG crops inside the image root.")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row["metadata"]["crop_sha256"]:
            raise ValueError(f"Crop differs from the saved model input: {path}")
        ship_id = row["metadata"].get("source_id")
        if not isinstance(ship_id, str) or not ship_id.strip():
            raise ValueError(f"Missing source ship ID for observation: {row['id']}")
        if ship_id in ship_ids:
            raise ValueError(f"Duplicate source ship ID: {ship_id}")
        ship_ids.add(ship_id)
        image_id = f"DEMO_{index:03d}"
        prepared.append((raw, {
            "observation_id": row["id"], "ship_id": ship_id,
            "observed_date": row["captured_at"][:10], "observed_at": row["captured_at"],
            "length_m": row["metadata"]["length_m"], "width_m": row["metadata"]["width_m"],
            "position": {"latitude": row["latitude"], "longitude": row["longitude"]},
            "classification": ("aircraft_carrier" if row["prediction"]["carrier_score"] >= threshold
                               else "not_aircraft_carrier"),
            "confidence": row["prediction"]["carrier_score"],
            "image_id": image_id, "image_file": image_id + path.suffix.lower(),
            "image_sha256": digest, "ground_truth_label": row["metadata"]["ground_truth_label"],
            "source_name": row["name"], "source_id": row["metadata"].get("source_id"),
        }))
    snapshot = {
        "schema_version": 1, "data_scope": "selected_demo_subset",
        "reference_date": LAST, "report_from": FIRST, "report_to": LAST,
        "source": {"project": "ShipClassification", "seed": seed, "model": report["model"],
                   "threshold": threshold, "run": run.name,
                   "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()},
        "observations": [row for _, row in prepared],
    }
    snapshot["snapshot_id"] = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8"),
    ).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    images = output / "images"
    images.mkdir(exist_ok=True)
    for raw, row in prepared:
        (images / row["image_file"]).write_bytes(raw)
    (output / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, default=PROJECT_ROOT.parent / "ShipClassification")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/demo")
    args = parser.parse_args()
    snapshot = write_snapshot(args.source_repo, args.output)
    print(json.dumps({"output": str(args.output.resolve()), "count": len(snapshot["observations"]),
                      "carrier_count": sum(r["classification"] == "aircraft_carrier"
                                           for r in snapshot["observations"]),
                      "report_from": FIRST, "report_to": LAST}, indent=2))


if __name__ == "__main__":
    main()
