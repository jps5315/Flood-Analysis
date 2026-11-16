from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def project_root() -> Path:
    """Return the repository root (parent of src/)."""
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required JSON file is missing: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_settings(path: Path | None = None) -> dict[str, Any]:
    settings_path = path or (project_root() / "config" / "settings.json")
    settings = _read_json(settings_path)
    _validate_settings(settings, settings_path)
    return settings


def load_schema(path: Path | None = None) -> dict[str, Any]:
    schema_path = path or (project_root() / "schema" / "impact_schema.json")
    schema = _read_json(schema_path)
    if "feature_classes" not in schema:
        raise ValueError(f"Schema is missing feature_classes: {schema_path}")
    return schema


def _validate_settings(settings: dict[str, Any], path: Path) -> None:
    required = ("client_crs", "impact_rule", "fields", "outputs", "qc")
    missing = [key for key in required if key not in settings]
    if missing:
        raise ValueError(f"{path} is missing keys: {', '.join(missing)}")
    wkid = settings["client_crs"].get("wkid")
    if not isinstance(wkid, int) or wkid <= 0:
        raise ValueError("client_crs.wkid must be a positive integer (3083 for Texas Albers).")
    rule = settings["impact_rule"]
    if rule.get("overlay_method") not in ("intersect", "vector_raster_hybrid"):
        raise ValueError("This build only supports overlay_method=intersect or vector_raster_hybrid (see docs/decisions.md ADR-002).")
    if rule.get("definition") not in ("overlap_threshold", "cumulative_compound", "cumulative_compound_3d"):
        raise ValueError("This build only supports definition=cumulative_compound_3d (see docs/decisions.md ADR-001).")
    for numeric in ("min_single_year_overlap_pct", "min_cumulative_overlap_pct", "min_cumulative_overlap_area_sf",
                    "min_single_year_cross_sectional_area_sf", "min_cumulative_cross_sectional_area_sf"):
        if not isinstance(rule.get(numeric), (int, float)):
            raise ValueError(f"impact_rule.{numeric} must be numeric.")
    if not isinstance(rule.get("historical_years"), list) or len(rule["historical_years"]) != 3:
        raise ValueError("impact_rule.historical_years must be a list of 3 years (e.g., [2016, 2017, 2018]).")
