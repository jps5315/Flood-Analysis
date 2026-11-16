from __future__ import annotations

from typing import Any

from .arcpy_support import project_to_client_crs, repair_if_needed
from .raster_analysis import hybrid_depth_analysis
from .rules import apply_impact_rule, collapse_parcel_overlaps
from .workspace import RunContext, scratch_path, spatial_evidence_path


def _first_value(row: dict[str, Any], candidates: list[str], default: str = "") -> str:
    lower = {k.lower(): v for k, v in row.items()}
    for name in candidates:
        value = lower.get(name.lower())
        if value not in (None, ""):
            return str(value)
    return default


def _resolve_existing_field(arcpy, dataset: str, field_name: str, required: bool = True) -> str | None:
    """Resolve a field name after geoprocessing may have changed its casing."""
    names = {field.name.lower(): field.name for field in arcpy.ListFields(dataset)}
    resolved = names.get(field_name.lower())
    if resolved is None and required:
        raise ValueError(
            f"Field {field_name!r} was not found in geoprocessing output {dataset!r}."
        )
    return resolved


def overlay_impact(
    arcpy,
    settings: dict[str, Any],
    ctx: RunContext,
    aoi_path: str,
    flood_paths: list[str],
    depth_raster_paths: list[str] | None,
    parcels_path: str,
    buildings_path: str | None,
    field_info: dict[str, Any],
    step_logger,
    logger,
) -> dict[str, Any]:
    wkid = int(settings["client_crs"]["wkid"])
    repair = bool(settings["qc"]["repair_geometry"])
    years = settings["impact_rule"]["historical_years"]
    overlay_method = settings["impact_rule"]["overlay_method"]

    if len(flood_paths) != len(years):
        raise ValueError(f"Expected {len(years)} flood inputs (one per year), got {len(flood_paths)}")

    # Step: Project inputs to client CRS
    step_id = step_logger.start_step(
        "Project inputs to client CRS",
        input_metadata={"aoi": aoi_path, "parcels": parcels_path, "floods": flood_paths},
        parameters={"wkid": wkid, "repair": repair},
    )

    aoi_p = project_to_client_crs(arcpy, aoi_path, scratch_path(ctx, "aoi_p"), wkid)
    parcels_p = project_to_client_crs(arcpy, parcels_path, scratch_path(ctx, "parcels_p"), wkid)
    for dataset in (aoi_p, parcels_p):
        repair_if_needed(arcpy, dataset, repair)

    parcels_clip = scratch_path(ctx, "parcels_clip")
    arcpy.analysis.Clip(parcels_p, aoi_p, parcels_clip)
    repair_if_needed(arcpy, parcels_clip, repair)

    aoi_parcel_count = int(arcpy.management.GetCount(parcels_clip)[0])
    logger.info("Clipped to AOI | parcels=%s", aoi_parcel_count)

    step_logger.complete_step(step_id, feature_counts={"parcels_clip": aoi_parcel_count})

    parcel_id_field = _resolve_existing_field(arcpy, parcels_clip, field_info["parcel_id_field"])
    parcel_areas = {
        str(row[0]): float(row[1] or 0.0)
        for row in arcpy.da.SearchCursor(parcels_clip, [parcel_id_field, "SHAPE@AREA"])
    }

    raw_rows: list[dict[str, Any]] = []
    cross_sectional_by_year: dict[int, dict[str, float]] = {}

    for year_idx, flood_path in enumerate(flood_paths):
        year = years[year_idx]
        
        # Step: Project and clip flood
        step_id = step_logger.start_step(
            f"Process flood year {year}",
            input_metadata={"flood_path": flood_path, "year": year},
            parameters={"repair": repair},
        )
        
        flood_p = project_to_client_crs(arcpy, flood_path, scratch_path(ctx, f"flood_{year}_p"), wkid)
        repair_if_needed(arcpy, flood_p, repair)

        flood_clip = scratch_path(ctx, f"flood_{year}_clip")
        arcpy.analysis.Clip(flood_p, aoi_p, flood_clip)
        repair_if_needed(arcpy, flood_clip, repair)

        # Retain spatial evidence: clipped flood
        evidence_flood_clip = spatial_evidence_path(ctx, f"flood_{year}_clip.gdb")
        arcpy.management.CreateFileGDB(str(ctx.spatial_evidence_dir / ctx.run_id), f"flood_{year}_clip.gdb")
        arcpy.management.CopyFeatures(flood_clip, f"{evidence_flood_clip}/flood_clip")

        flood_count = int(arcpy.management.GetCount(flood_clip)[0])
        logger.info("Year %s flood clipped | features=%s", year, flood_count)

        # Step: Intersect (2D overlap)
        intersect_out = scratch_path(ctx, f"parcel_flood_{year}_isect")
        arcpy.analysis.Intersect([parcels_clip, flood_clip], intersect_out, "ALL")
        repair_if_needed(arcpy, intersect_out, repair)

        # Retain spatial evidence: intersection
        evidence_intersect = spatial_evidence_path(ctx, f"parcel_flood_{year}_isect.gdb")
        arcpy.management.CreateFileGDB(str(ctx.spatial_evidence_dir / ctx.run_id), f"parcel_flood_{year}_isect.gdb")
        arcpy.management.CopyFeatures(intersect_out, f"{evidence_intersect}/parcel_flood_isect")

        isect_id_field = _resolve_existing_field(arcpy, intersect_out, field_info["parcel_id_field"])
        zone_field = field_info.get("flood_zone_field")
        if zone_field:
            zone_field = _resolve_existing_field(arcpy, intersect_out, zone_field, required=False)
        cursor_fields = [isect_id_field, "SHAPE@AREA"]
        if zone_field:
            cursor_fields.append(zone_field)
        with arcpy.da.SearchCursor(intersect_out, cursor_fields) as cursor:
            for rec in cursor:
                parcel_id = str(rec[0])
                overlap_area = float(rec[1] or 0.0)
                parcel_area = parcel_areas.get(parcel_id, 0.0)
                overlap_pct = (overlap_area / parcel_area * 100.0) if parcel_area > 0 else 0.0
                raw_rows.append(
                    {
                        "parcel_id": parcel_id,
                        "overlap_area_sf": overlap_area,
                        "overlap_pct": overlap_pct,
                        "parcel_area_sf": parcel_area,
                        "flood_zone": str(rec[2]) if zone_field else "",
                        "aoi_name": ctx.aoi_name,
                        "year": year,
                        "cross_sectional_area_sf": 0.0,
                    }
                )

        # Step: Calculate 3D cross-sectional area
        if overlay_method == "vector_raster_hybrid" and depth_raster_paths and len(depth_raster_paths) > year_idx:
            depth_raster = depth_raster_paths[year_idx]
            try:
                depth_stats = hybrid_depth_analysis(
                    arcpy, settings, flood_clip, depth_raster, parcels_clip, parcel_id_field, ctx.scratch_gdb, logger
                )
                cross_sectional_by_year[year] = depth_stats
                logger.info("Year %s: calculated cross-sectional area for %s parcels", year, len(depth_stats))
            except Exception as exc:
                logger.warning("Year %s cross-sectional analysis failed: %s", year, exc)
                cross_sectional_by_year[year] = {}

        step_logger.complete_step(step_id, feature_counts={"flood_clip": flood_count, "intersect_rows": len(raw_rows)})

    # Merge cross-sectional area results
    for row in raw_rows:
        year = row["year"]
        parcel_id = row["parcel_id"]
        if year in cross_sectional_by_year and parcel_id in cross_sectional_by_year[year]:
            row["cross_sectional_area_sf"] = cross_sectional_by_year[year][parcel_id].get("cross_sectional_area_sf", 0.0)

    collapsed = collapse_parcel_overlaps(raw_rows)
    logger.info("Total intersect rows=%s collapsed parcels=%s", len(raw_rows), len(collapsed))

    building_hits: dict[str, int] = {}
    if buildings_path and settings["impact_rule"].get("use_buildings_if_present", True):
        flood_clip = scratch_path(ctx, "flood_combined_clip")
        arcpy.management.Merge([scratch_path(ctx, f"flood_{y}_clip") for y in years], flood_clip)
        building_hits = _count_flooded_buildings(
            arcpy, settings, ctx, buildings_path, flood_clip, parcels_clip, parcel_id_field, logger
        )
        for item in collapsed:
            item["building_count"] = building_hits.get(item["parcel_id"], 0)
    else:
        for item in collapsed:
            item["building_count"] = 0

    impacted_rows = []
    for item in collapsed:
        flag, note = apply_impact_rule(
            item["cumulative_overlap_pct"],
            item["max_single_year_overlap_pct"],
            item["cumulative_overlap_area_sf"],
            item["cumulative_cross_sectional_area_sf"],
            item["max_single_year_cross_sectional_area_sf"],
            settings,
        )
        item["impact_flag"] = flag
        item["qc_notes"] = note
        if item.get("overlap_capped"):
            item["qc_notes"] = (item["qc_notes"] + ";overlap_capped_to_parcel_area").strip(";")
        if flag == 1:
            impacted_rows.append(item)

    # Retain spatial evidence: final parcels
    evidence_parcels = spatial_evidence_path(ctx, "parcels_final.gdb")
    arcpy.management.CreateFileGDB(str(ctx.spatial_evidence_dir / ctx.run_id), "parcels_final.gdb")
    arcpy.management.CopyFeatures(parcels_clip, f"{evidence_parcels}/parcels_clip")

    return {
        "aoi_parcel_count": aoi_parcel_count,
        "collapsed": collapsed,
        "impacted_rows": impacted_rows,
        "parcels_clip": parcels_clip,
        "parcel_id_field": parcel_id_field,
        "building_hits": building_hits,
    }


def _geometry_area_field(arcpy, dataset: str) -> str:
    names = [f.name for f in arcpy.ListFields(dataset)]
    for candidate in ("POLY_AREA", "AREA", "Shape_Area"):
        if candidate in names:
            return candidate
    raise RuntimeError(f"No area field found after AddGeometryAttributes on {dataset}: {names}")


def _count_flooded_buildings(
    arcpy,
    settings: dict[str, Any],
    ctx: RunContext,
    buildings_path: str,
    flood_clip: str,
    parcels_clip: str,
    parcel_id_field: str,
    logger,
) -> dict[str, int]:
    wkid = int(settings["client_crs"]["wkid"])
    buildings_p = project_to_client_crs(arcpy, buildings_path, scratch_path(ctx, "buildings_p"), wkid)
    repair_if_needed(arcpy, buildings_p, bool(settings["qc"]["repair_geometry"]))
    buildings_clip = scratch_path(ctx, "buildings_clip")
    arcpy.analysis.Clip(buildings_p, parcels_clip, buildings_clip)
    flooded_buildings = scratch_path(ctx, "buildings_flood")
    arcpy.analysis.Intersect([buildings_clip, flood_clip], flooded_buildings, "ONLY_FID")
    joined = scratch_path(ctx, "buildings_on_parcels")
    arcpy.analysis.SpatialJoin(
        flooded_buildings,
        parcels_clip,
        joined,
        "JOIN_ONE_TO_ONE",
        "KEEP_COMMON",
        match_option="INTERSECT",
    )
    counts: dict[str, int] = {}
    with arcpy.da.SearchCursor(joined, [parcel_id_field]) as cursor:
        for (parcel_id,) in cursor:
            key = str(parcel_id)
            counts[key] = counts.get(key, 0) + 1
    logger.info("Buildings intersecting flood and parcels: %s", sum(counts.values()))
    return counts
