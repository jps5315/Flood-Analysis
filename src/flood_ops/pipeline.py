from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analysis import overlay_impact
from .config import load_schema, load_settings
from .logging_setup import configure_logging
from .publish import (
    insert_failure_row,
    insert_run_row,
    write_outputs,
)
from .report import write_reports
from .step_log import StepLogger
from .validate import qc_results, require_arcpy, validate_inputs, ValidationError
from .workspace import prepare_run, spatial_evidence_path


def run_flood_impact(
    aoi_path: str,
    flood_paths: list[str] | str,
    parcels_path: str,
    output_workspace: str,
    scratch_folder: str,
    scenario_name: str = "Cumulative_3Year_Flood",
    aoi_name: str = "AOI",
    buildings_path: str | None = None,
    depth_raster_paths: list[str] | str | None = None,
    run_id: str | None = None,
    settings_path: str | None = None,
    layout_aprx: str | None = None,
    arcpy_messages=None,
) -> dict[str, Any]:
    """End-to-end flood impact run. Toolbox and CLI both call this."""
    arcpy = require_arcpy()
    settings = load_settings(Path(settings_path) if settings_path else None)

    # Handle backward compatibility: flood_paths can be a list or single string
    if isinstance(flood_paths, str):
        flood_paths = [flood_paths]

    # Handle depth raster paths
    if isinstance(depth_raster_paths, str):
        depth_raster_paths = [depth_raster_paths]
    elif depth_raster_paths is None:
        depth_raster_paths = []

    ctx = prepare_run(
        arcpy,
        settings,
        output_workspace=output_workspace,
        scratch_folder=scratch_folder,
        scenario_name=scenario_name,
        aoi_name=aoi_name,
        run_id=run_id,
    )
    logger = configure_logging(ctx.log_dir, ctx.run_id, arcpy_messages)
    step_logger = StepLogger(ctx.run_id, ctx.log_dir, int(settings["client_crs"]["wkid"]))
    logger.info("Starting run %s | scenario=%s aoi=%s", ctx.run_id, scenario_name, aoi_name)

    # Capture input metadata for failure tracking
    input_metadata = {
        "aoi_path": aoi_path,
        "flood_paths": flood_paths,
        "depth_raster_paths": depth_raster_paths,
        "parcels_path": parcels_path,
        "buildings_path": buildings_path,
        "overlay_method": settings["impact_rule"]["overlay_method"],
        "crs_wkid": settings["client_crs"]["wkid"],
    }

    # Write IN_PROGRESS record to runs table
    schema = load_schema()
    names = settings["outputs"]
    gdb = ctx.production_gdb
    from .arcpy_support import create_feature_class_from_schema
    runs_tbl = create_feature_class_from_schema(
        arcpy, gdb, names["runs_table"], schema["feature_classes"]["FloodImpact_Runs"], int(settings["client_crs"]["wkid"])
    )
    insert_run_row(arcpy, runs_tbl, ctx, "IN_PROGRESS", input_metadata)

    try:
        field_info = validate_inputs(
            arcpy, settings, aoi_path, flood_paths, parcels_path, buildings_path, logger
        )
        flood_counts = field_info.get("flood_counts")
        if flood_counts is None:
            flood_counts = [
                int(arcpy.management.GetCount(path)[0]) for path in flood_paths
            ]
        # Update input metadata with validation results
        input_metadata.update({
            "aoi_count": field_info["aoi_count"],
            "flood_counts": flood_counts,
            "parcel_count": field_info["parcel_count"],
            "building_count": field_info["building_count"],
        })

        if field_info.get("aoi_name_field") and aoi_name == "AOI":
            ctx.aoi_name = _read_first(arcpy, aoi_path, field_info["aoi_name_field"]) or aoi_name
        overlay = overlay_impact(
            arcpy, settings, ctx, aoi_path, flood_paths, depth_raster_paths, parcels_path, buildings_path, field_info, step_logger, logger
        )
        qc_results(settings, len(overlay["impacted_rows"]), logger)
        outputs = write_outputs(arcpy, settings, ctx, overlay, logger)
        reports = write_reports(arcpy, settings, ctx, overlay, outputs, layout_aprx, logger)

        # Write step log
        step_logger.write_log()

        # Update runs table with SUCCEEDED status and result summary
        result_summary = {
            "impacted_count": len(overlay["impacted_rows"]),
            "parcel_count": overlay["aoi_parcel_count"],
            "impacted_cross_sectional_area_sf": sum(r["cumulative_cross_sectional_area_sf"] for r in overlay["impacted_rows"]),
        }
        insert_run_row(arcpy, runs_tbl, ctx, "SUCCEEDED", input_metadata, result_summary)

        logger.info("Run %s succeeded.", ctx.run_id)
        return {
            "run_id": ctx.run_id,
            "impacted_count": len(overlay["impacted_rows"]),
            "parcel_count": overlay["aoi_parcel_count"],
            "outputs": outputs,
            "reports": reports,
            "scratch_gdb": ctx.scratch_gdb,
        }
    except ValidationError as exc:
        logger.exception("Validation failed for run %s", ctx.run_id)
        step_logger.write_log()
        # Write failure record with next steps
        next_steps = [
            "Check AOI geometry (must be polygon)",
            "Verify flood scenarios are valid polygons",
            "Ensure parcels have required ID field",
            "Check feature counts against QC guardrails",
        ]
        insert_failure_row(arcpy, runs_tbl, ctx, "VALIDATION", str(exc), next_steps, input_metadata)
        raise
    except Exception as exc:
        logger.exception("Run %s failed", ctx.run_id)
        step_logger.write_log()
        # Write failure record with next steps
        next_steps = [
            "Check ArcPy environment and licensing",
            "Verify input paths exist and are accessible",
            "Review logs for specific error details",
            "Ensure sufficient disk space for scratch GDB",
        ]
        insert_failure_row(arcpy, runs_tbl, ctx, "EXECUTION", str(exc), next_steps, input_metadata)
        raise


def _read_first(arcpy, path: str, field_name: str) -> str:
    with arcpy.da.SearchCursor(path, [field_name]) as cursor:
        for (value,) in cursor:
            if value:
                return str(value)
            break
    return ""
