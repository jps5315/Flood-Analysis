from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from typing import Any

from .arcpy_support import create_feature_class_from_schema, delete_run_rows
from .config import load_schema
from .validate import validate_schema_fields
from .workspace import RunContext, production_path


PARCEL_FIELDS = [
    "run_id",
    "run_time_utc",
    "scenario_name",
    "aoi_name",
    "parcel_id",
    "flood_zone",
    "parcel_area_sf",
    "overlap_area_sf",
    "overlap_pct",
    "cumulative_overlap_area_sf",
    "cumulative_overlap_pct",
    "max_single_year_overlap_pct",
    "cross_sectional_area_sf",
    "cumulative_cross_sectional_area_sf",
    "max_single_year_cross_sectional_area_sf",
    "years_with_flood_count",
    "impact_flag",
    "impact_rule",
    "building_count",
    "qc_notes",
    "SHAPE@",
]


def write_outputs(
    arcpy,
    settings: dict[str, Any],
    ctx: RunContext,
    overlay: dict[str, Any],
    logger,
) -> dict[str, str]:
    schema = load_schema()
    wkid = int(settings["client_crs"]["wkid"])
    names = settings["outputs"]
    gdb = ctx.production_gdb

    history_fc = create_feature_class_from_schema(
        arcpy, gdb, names["history_parcels"], schema["feature_classes"]["ImpactedParcels"], wkid
    )
    latest_fc = create_feature_class_from_schema(
        arcpy, gdb, names["latest_parcels"], schema["feature_classes"]["ImpactedParcels"], wkid
    )
    history_tbl = create_feature_class_from_schema(
        arcpy, gdb, names["history_summary"], schema["feature_classes"]["ImpactSummary"], wkid
    )
    latest_tbl = create_feature_class_from_schema(
        arcpy, gdb, names["latest_summary"], schema["feature_classes"]["ImpactSummary"], wkid
    )
    runs_tbl = create_feature_class_from_schema(
        arcpy, gdb, names["runs_table"], schema["feature_classes"]["FloodImpact_Runs"], wkid
    )

    for dataset, key in (
        (history_fc, "ImpactedParcels"),
        (latest_fc, "ImpactedParcels"),
        (history_tbl, "ImpactSummary"),
        (latest_tbl, "ImpactSummary"),
        (runs_tbl, "FloodImpact_Runs"),
    ):
        validate_schema_fields(arcpy, dataset, key)

    # ADR-004: Append-only for history tables. No delete before write.
    # Only Latest tables are replaced on successful run.
    arcpy.management.DeleteRows(latest_fc)
    arcpy.management.DeleteRows(latest_tbl)

    geom_by_id = _parcel_geometries(arcpy, overlay["parcels_clip"], overlay["parcel_id_field"])
    rule_name = settings["impact_rule"]["definition"]
    rows_to_write = overlay["collapsed"]
    insert_parcel_rows(arcpy, history_fc, ctx, rows_to_write, geom_by_id, rule_name)
    insert_parcel_rows(arcpy, latest_fc, ctx, rows_to_write, geom_by_id, rule_name)

    summary = build_summary_row(ctx, overlay, settings, rule_name)
    insert_summary_row(arcpy, history_tbl, summary)
    insert_summary_row(arcpy, latest_tbl, summary)

    logger.info(
        "Wrote production outputs | history=%s latest=%s summary_impacted=%s",
        names["history_parcels"],
        names["latest_parcels"],
        summary["impacted_count"],
    )
    return {
        "history_parcels": history_fc,
        "latest_parcels": latest_fc,
        "history_summary": history_tbl,
        "latest_summary": latest_tbl,
        "runs_table": runs_tbl,
        "production_gdb": gdb,
    }


def _parcel_geometries(arcpy, parcels_clip: str, parcel_id_field: str) -> dict[str, Any]:
    geoms = {}
    with arcpy.da.SearchCursor(parcels_clip, [parcel_id_field, "SHAPE@"]) as cursor:
        for parcel_id, geom in cursor:
            geoms[str(parcel_id)] = geom
    return geoms


def insert_parcel_rows(arcpy, fc: str, ctx: RunContext, rows: list[dict], geoms: dict, rule_name: str) -> None:
    with arcpy.da.InsertCursor(fc, PARCEL_FIELDS) as cursor:
        for row in rows:
            geom = geoms.get(row["parcel_id"])
            if geom is None:
                continue
            cursor.insertRow(
                [
                    ctx.run_id,
                    ctx.run_time_utc.replace(tzinfo=None),
                    ctx.scenario_name,
                    ctx.aoi_name,
                    row["parcel_id"],
                    row.get("flood_zone") or "",
                    row["parcel_area_sf"],
                    row["overlap_area_sf"],
                    row["overlap_pct"],
                    row["cumulative_overlap_area_sf"],
                    row["cumulative_overlap_pct"],
                    row["max_single_year_overlap_pct"],
                    row["cross_sectional_area_sf"],
                    row["cumulative_cross_sectional_area_sf"],
                    row["max_single_year_cross_sectional_area_sf"],
                    row["years_with_flood_count"],
                    int(row["impact_flag"]),
                    rule_name,
                    int(row.get("building_count") or 0),
                    row.get("qc_notes") or "",
                    geom,
                ]
            )


def build_summary_row(ctx: RunContext, overlay: dict[str, Any], settings: dict[str, Any], rule_name: str) -> dict:
    impacted = overlay["impacted_rows"]
    parcel_count = overlay["aoi_parcel_count"]
    impacted_count = len(impacted)
    impacted_area = sum(r["cumulative_overlap_area_sf"] for r in impacted)
    impacted_cross_sectional = sum(r["cumulative_cross_sectional_area_sf"] for r in impacted)
    building_count = sum(r.get("building_count", 0) for r in impacted)
    max_single_pct = max((r["max_single_year_overlap_pct"] for r in overlay["collapsed"]), default=0.0)
    max_cumulative_pct = max((r["cumulative_overlap_pct"] for r in overlay["collapsed"]), default=0.0)
    max_cross_sectional = max((r["max_single_year_cross_sectional_area_sf"] for r in overlay["collapsed"]), default=0.0)
    impacted_pct = (impacted_count / parcel_count * 100.0) if parcel_count else 0.0
    return {
        "run_id": ctx.run_id,
        "run_time_utc": ctx.run_time_utc.replace(tzinfo=None),
        "scenario_name": ctx.scenario_name,
        "aoi_name": ctx.aoi_name,
        "parcel_count": parcel_count,
        "impacted_count": impacted_count,
        "impacted_pct": impacted_pct,
        "impacted_area_sf": impacted_area,
        "impacted_cross_sectional_area_sf": impacted_cross_sectional,
        "building_count": building_count,
        "max_overlap_pct": max_single_pct,
        "max_cumulative_overlap_pct": max_cumulative_pct,
        "max_cross_sectional_area_sf": max_cross_sectional,
        "impact_rule": rule_name,
    }


def insert_summary_row(arcpy, table: str, row: dict) -> None:
    fields = [
        "run_id",
        "run_time_utc",
        "scenario_name",
        "aoi_name",
        "parcel_count",
        "impacted_count",
        "impacted_pct",
        "impacted_area_sf",
        "impacted_cross_sectional_area_sf",
        "building_count",
        "max_overlap_pct",
        "max_cumulative_overlap_pct",
        "max_cross_sectional_area_sf",
        "impact_rule",
    ]
    with arcpy.da.InsertCursor(table, fields) as cursor:
        cursor.insertRow([row[name] for name in fields])


def insert_run_row(arcpy, table: str, ctx: RunContext, status: str, input_metadata: dict[str, Any], result_summary: dict[str, Any] | None = None, failure_summary: dict[str, Any] | None = None) -> None:
    version_id = _get_version_id()
    schema = load_schema()
    run_fields = {
        field["name"]: field
        for field in schema["feature_classes"]["FloodImpact_Runs"]["fields"]
    }
    fields = [
        "run_id",
        "version_id",
        "run_time_utc",
        "completion_time_utc",
        "status",
        "scenario_name",
        "aoi_name",
        "input_metadata",
        "result_summary",
        "failure_summary",
    ]
    with arcpy.da.InsertCursor(table, fields) as cursor:
        cursor.insertRow(
            [
                ctx.run_id,
                version_id,
                ctx.run_time_utc.replace(tzinfo=None),
                datetime.now(timezone.utc).replace(tzinfo=None),
                status,
                ctx.scenario_name,
                ctx.aoi_name,
                json.dumps(input_metadata),
                json.dumps(result_summary) if result_summary else None,
                _serialize_failure_summary(
                    failure_summary,
                    run_fields["failure_summary"]["length"],
                )
                if failure_summary
                else None,
            ]
        )


def _serialize_failure_summary(summary: dict[str, Any], max_length: int) -> str:
    """Keep the failure record valid JSON while fitting its geodatabase field."""
    bounded = dict(summary)
    encoded = json.dumps(bounded, separators=(",", ":"))
    if len(encoded) <= max_length:
        return encoded

    stack_trace = str(bounded.get("stack_trace", ""))
    error_message = str(bounded.get("error_message", ""))
    next_steps = bounded.get("next_steps", [])

    while len(encoded) > max_length and stack_trace:
        excess = len(encoded) - max_length
        stack_trace = stack_trace[: max(0, len(stack_trace) - excess - 16)]
        bounded["stack_trace"] = stack_trace + "\n[truncated]"
        encoded = json.dumps(bounded, separators=(",", ":"))

    while len(encoded) > max_length and error_message:
        excess = len(encoded) - max_length
        error_message = error_message[: max(0, len(error_message) - excess - 16)]
        bounded["error_message"] = error_message + " [truncated]"
        encoded = json.dumps(bounded, separators=(",", ":"))

    while len(encoded) > max_length and next_steps:
        next_steps = next_steps[:-1]
        bounded["next_steps"] = next_steps
        encoded = json.dumps(bounded, separators=(",", ":"))

    if len(encoded) > max_length:
        bounded = {"error_type": str(bounded.get("error_type", "ERROR"))[:64]}
        encoded = json.dumps(bounded, separators=(",", ":"))
    if len(encoded) > max_length:
        raise ValueError(f"Failure summary field limit is too small: {max_length}.")
    return encoded


def insert_failure_row(
    arcpy,
    table: str,
    ctx: RunContext,
    error_type: str,
    error_message: str,
    next_steps: list[str],
    input_metadata: dict[str, Any],
) -> None:
    """Write a failure record when a run fails. This preserves audit trail."""
    failure_summary = {
        "error_type": error_type,
        "error_message": error_message,
        "next_steps": next_steps,
        "stack_trace": traceback.format_exc(),
    }
    insert_run_row(
        arcpy,
        table,
        ctx,
        "FAILED",
        input_metadata,
        result_summary=None,
        failure_summary=failure_summary,
    )


def _get_version_id() -> str:
    """Generate a version ID from git or fallback to semantic version."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:40]
    except Exception:
        pass
    return "v3.0.0"  # Fallback to schema version
