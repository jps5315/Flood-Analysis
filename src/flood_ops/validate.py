from __future__ import annotations

from typing import Any, Iterable, Optional
from pathlib import Path
import logging

from .config import load_schema
from .rest_loader import RestLoader

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Fail-fast input or QC error. Do not catch and continue the run."""


def require_arcpy():
    try:
        import arcpy  # type: ignore
    except ImportError as exc:
        raise ValidationError(
            "ArcPy is not available. Run this toolbox with ArcGIS Pro / Server Python "
            "(arcgispro-py3), not a generic CPython install."
        ) from exc
    return arcpy


def is_rest_url(path: str) -> bool:
    """Check if path is an ArcGIS REST URL."""
    return path.startswith(("http://", "https://")) and "/rest/" in path.lower()


def dataset_exists(arcpy, path: str, label: str) -> None:
    if not path:
        raise ValidationError(f"{label} is required.")
    if is_rest_url(path):
        # REST URLs are validated separately
        return
    if not arcpy.Exists(path):
        raise ValidationError(f"{label} does not exist: {path}")


def count_features(arcpy, path: str) -> int:
    return int(arcpy.management.GetCount(path)[0])


def describe_dataset(arcpy, path: str):
    return arcpy.Describe(path)


def assert_polygon(arcpy, path: str, label: str) -> None:
    if is_rest_url(path):
        # REST geometry type is validated during load
        return
    shape = describe_dataset(arcpy, path).shapeType.upper()
    if shape not in {"POLYGON", "MULTIPOLYGON"}:
        raise ValidationError(f"{label} must be polygon geometry, found {shape}: {path}")


def field_names(arcpy, path: str) -> list[str]:
    return [field.name for field in arcpy.ListFields(path)]


def resolve_field(arcpy, path: str, candidates: Iterable[str], label: str, required: bool = True) -> str | None:
    names = {name.lower(): name for name in field_names(arcpy, path)}
    for candidate in candidates:
        if candidate.lower() in names:
            return names[candidate.lower()]
    if required:
        raise ValidationError(
            f"{label} is missing a required identifier field. Looked for {list(candidates)} in {path}."
        )
    return None


def validate_inputs(
    arcpy,
    settings: dict[str, Any],
    aoi_path: str,
    flood_paths: list[str] | str,
    parcels_path: str,
    buildings_path: str | None,
    logger,
) -> dict[str, Any]:
    """Cheap checks that must pass before any overlay. This is the 2 AM safety net."""
    qc = settings["qc"]

    # Handle backward compatibility: flood_paths can be a list or single string
    if isinstance(flood_paths, str):
        flood_paths = [flood_paths]

    years = settings["impact_rule"]["historical_years"]
    if len(flood_paths) != len(years):
        raise ValidationError(
            f"Expected {len(years)} flood inputs (one per year: {years}), got {len(flood_paths)}."
        )

    for path, label in (
        (aoi_path, "AOI"),
        (parcels_path, "Parcels"),
    ):
        dataset_exists(arcpy, path, label)
        assert_polygon(arcpy, path, label)

    for idx, flood_path in enumerate(flood_paths):
        label = f"Flood scenario (year {years[idx]})"
        dataset_exists(arcpy, flood_path, label)
        assert_polygon(arcpy, flood_path, label)

    aoi_count = count_features(arcpy, aoi_path)
    parcel_count = count_features(arcpy, parcels_path)
    flood_counts = [count_features(arcpy, fp) for fp in flood_paths]

    if qc["fail_on_empty_aoi"] and aoi_count == 0:
        raise ValidationError("AOI has 0 features.")
    if qc["fail_on_empty_flood"] and all(fc == 0 for fc in flood_counts):
        raise ValidationError("All flood scenarios have 0 features.")
    if qc["fail_on_empty_parcels"] and parcel_count == 0:
        raise ValidationError("Parcels have 0 features.")

    if aoi_count > qc["max_aoi_features"]:
        raise ValidationError(
            f"AOI has {aoi_count} features; max is {qc['max_aoi_features']}. "
            "Run one incident/watershed at a time."
        )
    for idx, flood_count in enumerate(flood_counts):
        if flood_count > qc["max_flood_features"]:
            raise ValidationError(
                f"Flood layer (year {years[idx]}) has {flood_count} features; max is {qc['max_flood_features']}."
            )
    if parcel_count > qc["max_parcel_features"]:
        raise ValidationError(
            f"Parcels have {parcel_count} features; max is {qc['max_parcel_features']}. "
            "Clip to the AOI before this tool, or raise the guardrail deliberately."
        )

    parcel_id_field = resolve_field(arcpy, parcels_path, settings["fields"]["parcel_id_candidates"], "Parcels")
    # Resolve flood zone field from the first flood input (assume consistent schema across years)
    flood_zone_field = resolve_field(
        arcpy, flood_paths[0], settings["fields"]["flood_zone_candidates"], "Flood", required=False
    )
    aoi_name_field = resolve_field(
        arcpy, aoi_path, settings["fields"]["aoi_name_candidates"], "AOI", required=False
    )

    building_id_field = None
    building_count = 0
    if buildings_path:
        dataset_exists(arcpy, buildings_path, "Buildings")
        assert_polygon(arcpy, buildings_path, "Buildings")
        building_count = count_features(arcpy, buildings_path)
        if building_count > qc["max_building_features"]:
            raise ValidationError(
                f"Buildings have {building_count} features; max is {qc['max_building_features']}."
            )
        building_id_field = resolve_field(
            arcpy, buildings_path, settings["fields"]["building_id_candidates"], "Buildings", required=False
        )

    logger.info(
        "Input counts | aoi=%s flood_by_year=%s parcels=%s buildings=%s",
        aoi_count,
        dict(zip(years, flood_counts)),
        parcel_count,
        building_count,
    )
    return {
        "aoi_count": aoi_count,
        "flood_counts": flood_counts,
        "parcel_count": parcel_count,
        "building_count": building_count,
        "parcel_id_field": parcel_id_field,
        "flood_zone_field": flood_zone_field,
        "aoi_name_field": aoi_name_field,
        "building_id_field": building_id_field,
    }


def validate_schema_fields(arcpy, feature_class: str, schema_key: str) -> None:
    schema = load_schema()
    expected = {field["name"].lower() for field in schema["feature_classes"][schema_key]["fields"]}
    actual = {name.lower() for name in field_names(arcpy, feature_class)}
    missing = expected - actual
    if missing:
        raise ValidationError(
            f"{feature_class} is missing contracted fields {sorted(missing)}. "
            "Do not invent aliases. Recreate from schema."
        )


def qc_results(settings: dict[str, Any], impacted_count: int, logger) -> None:
    qc = settings["qc"]
    if impacted_count == 0:
        message = "Overlay produced 0 impacted parcels. Check AOI, flood scenario, and CRS."
        if qc["fail_on_empty_impact"]:
            raise ValidationError(message)
        if qc["warn_on_empty_impact"]:
            logger.warning(message)


def load_rest_input(
    rest_url: str,
    output_path: Path,
    settings: dict[str, Any],
    where_clause: str = "1=1",
    spatial_reference: Optional[int] = None,
    geometry_filter: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Load data from ArcGIS REST URL with pagination support.

    Args:
        rest_url: ArcGIS REST service URL
        output_path: Output GeoJSON file path
        settings: Settings dict with QC config
        where_clause: SQL where clause
        spatial_reference: Output CRS WKID
        geometry_filter: Optional geometry filter (e.g., bbox)

    Returns:
        Dict with pagination info and feature count
    """
    qc = settings["qc"]

    loader = RestLoader(
        pagination_threshold=qc["pagination_threshold"],
        pagination_record_count=qc["pagination_record_count"],
        timeout=qc["rest_timeout_seconds"]
    )

    logger.info(f"Loading data from REST: {rest_url}")

    # Query features with pagination
    features, pagination_info = loader.query_features(
        rest_url,
        where_clause=where_clause,
        out_fields="*",
        spatial_reference=spatial_reference,
        geometry_filter=geometry_filter
    )

    # Save to GeoJSON
    metadata = {
        'source_url': rest_url,
        'query_where': where_clause,
        'output_crs': spatial_reference,
        'pagination_info': pagination_info
    }

    loader.save_to_geojson(features, output_path, metadata)

    logger.info(
        f"Loaded {len(features)} features from REST (pagination: {pagination_info['use_pagination']}, "
        f"cycles: {pagination_info['pagination_cycles']})"
    )

    return {
        'feature_count': len(features),
        'pagination_info': pagination_info
    }
