"""Vector-raster hybrid flood depth analysis.

Portal raster analysis (primary) and local fallback (raster-to-points + spatial join).
This module handles the cross-sectional area (volume) calculation from depth rasters.
"""
from __future__ import annotations

import os
from typing import Any

from .validate import ValidationError


def analyze_depth_with_portal(
    portal_url: str,
    portal_username: str,
    portal_password: str,
    flood_polygons_path: str,
    depth_raster_url: str,
    parcels_path: str,
    parcel_id_field: str,
    logger,
) -> dict[str, Any]:
    """Use ArcGIS Enterprise Portal to perform zonal statistics on depth raster.

    This is the primary method when Portal is available and licensed.
    Requires: arcgis package (pip install arcgis)

    Args:
        portal_url: Enterprise Portal URL (e.g., https://portal.example.com/portal)
        portal_username: Portal username
        portal_password: Portal password (or from environment variable)
        flood_polygons_path: Path to flood polygon layer (used to select parcels)
        depth_raster_url: URL of depth raster image service
        parcels_path: Path to parcels feature class
        parcel_id_field: Field name for parcel ID
        logger: Logger instance

    Returns:
        Dictionary with cross-sectional area statistics per parcel
    """
    try:
        from arcgis.gis import GIS
        from arcgis.raster import ImageryLayer
    except ImportError as exc:
        logger.warning("ArcGIS API for Python not installed. Falling back to local method.")
        raise ValidationError(
            "Portal raster analysis requires arcgis package. Install with: pip install arcgis"
        ) from exc

    logger.info("Connecting to Portal: %s", portal_url)
    gis = GIS(portal_url, username=portal_username, password=portal_password)

    logger.info("Loading depth raster from: %s", depth_raster_url)
    depth_layer = ImageryLayer(depth_raster_url, gis)

    # TODO: Implement actual zonal statistics using Portal raster analysis
    # This requires Image Service with analysis capability enabled
    # For now, return placeholder to demonstrate architecture
    logger.warning("Portal zonal statistics not yet fully implemented. Use local fallback.")
    return {}


def analyze_depth_local_fallback(
    arcpy,
    flood_polygons_path: str,
    depth_raster_path: str,
    parcels_path: str,
    parcel_id_field: str,
    scratch_gdb: str,
    logger,
) -> dict[str, Any]:
    """Local fallback: raster-to-points + spatial join.

    Does not require Spatial Analyst license.
    Steps:
    1. Convert depth raster to points (each point = one cell with depth value)
    2. Select points within flood polygons
    3. Spatial join points to parcels to aggregate depth statistics
    4. Calculate cross-sectional area from aggregated depth

    Args:
        arcpy: ArcPy module
        flood_polygons_path: Path to flood polygon layer
        depth_raster_path: Path to depth raster
        parcels_path: Path to parcels feature class
        parcel_id_field: Field name for parcel ID
        scratch_gdb: Path to scratch geodatabase
        logger: Logger instance

    Returns:
        Dictionary with cross-sectional area statistics per parcel
    """
    logger.info("Using local fallback: raster-to-points + spatial join")

    # Step 1: Convert raster to points
    raster_points = f"{scratch_gdb}\\raster_points"
    arcpy.conversion.RasterToPoint(depth_raster_path, raster_points)
    point_count = int(arcpy.management.GetCount(raster_points)[0])
    logger.info("Converted raster to %s points", point_count)

    # Step 2: Select points within flood polygons
    points_in_flood = f"{scratch_gdb}\\points_in_flood"
    arcpy.analysis.SelectLayerByLocation(raster_points, "INTERSECT", flood_polygons_path)
    arcpy.management.CopyFeatures(raster_points, points_in_flood)
    selected_count = int(arcpy.management.GetCount(points_in_flood)[0])
    logger.info("Selected %s points within flood extent", selected_count)

    # Step 3: Spatial join points to parcels
    joined = f"{scratch_gdb}\\points_on_parcels"
    arcpy.analysis.SpatialJoin(
        points_in_flood,
        parcels_path,
        joined,
        "JOIN_ONE_TO_ONE",
        "KEEP_COMMON",
        match_option="INTERSECT",
    )

    # Step 4: Aggregate depth statistics per parcel
    # Assume raster points have a 'GRID_CODE' field with depth value
    depth_field = "GRID_CODE"
    stats: dict[str, dict[str, Any]] = {}

    with arcpy.da.SearchCursor(joined, [parcel_id_field, depth_field]) as cursor:
        for parcel_id, depth in cursor:
            pid = str(parcel_id)
            if pid not in stats:
                stats[pid] = {"sum_depth": 0.0, "count": 0}
            stats[pid]["sum_depth"] += float(depth or 0.0)
            stats[pid]["count"] += 1

    # Calculate cross-sectional area (volume) for each parcel
    # Get parcel areas
    parcel_areas = {
        str(row[0]): float(row[1] or 0.0)
        for row in arcpy.da.SearchCursor(parcels_path, [parcel_id_field, "SHAPE@AREA"])
    }

    results = {}
    for pid, stat in stats.items():
        parcel_area = parcel_areas.get(pid, 0.0)
        # Cross-sectional area = average depth × parcel area
        # This is an approximation; true zonal statistics would be more accurate
        avg_depth = stat["sum_depth"] / stat["count"] if stat["count"] > 0 else 0.0
        cross_sectional_area = avg_depth * parcel_area
        results[pid] = {
            "cross_sectional_area_sf": cross_sectional_area,
            "avg_depth_ft": avg_depth,
            "point_count": stat["count"],
        }

    logger.info("Calculated cross-sectional area for %s parcels", len(results))
    return results


def hybrid_depth_analysis(
    arcpy,
    settings: dict[str, Any],
    flood_polygons_path: str,
    depth_raster_path: str,
    parcels_path: str,
    parcel_id_field: str,
    scratch_gdb: str,
    logger,
) -> dict[str, Any]:
    """Try Portal raster analysis first, fall back to local method.

    Args:
        arcpy: ArcPy module
        settings: Settings dictionary with portal config
        flood_polygons_path: Path to flood polygon layer
        depth_raster_path: Path to depth raster (local) or URL (Portal)
        parcels_path: Path to parcels feature class
        parcel_id_field: Field name for parcel ID
        scratch_gdb: Path to scratch geodatabase
        logger: Logger instance

    Returns:
        Dictionary with cross-sectional area statistics per parcel
    """
    portal_config = settings.get("portal", {})
    use_portal = portal_config.get("use_portal_for_raster_analysis", True)
    fallback_enabled = portal_config.get("fallback_to_local", True)

    portal_url = portal_config.get("url", "")
    portal_username = portal_config.get("username", "")
    portal_password = os.environ.get("FLOOD_OPS_PORTAL_PASSWORD") or portal_config.get("password", "")

    if use_portal and portal_url and portal_username:
        try:
            logger.info("Attempting Portal raster analysis...")
            return analyze_depth_with_portal(
                portal_url,
                portal_username,
                portal_password,
                flood_polygons_path,
                depth_raster_path,
                parcels_path,
                parcel_id_field,
                logger,
            )
        except Exception as exc:
            if fallback_enabled:
                logger.warning("Portal analysis failed: %s. Falling back to local method.", exc)
            else:
                raise ValidationError("Portal raster analysis failed and fallback is disabled.") from exc

    logger.info("Using local fallback for depth analysis")
    return analyze_depth_local_fallback(
        arcpy,
        flood_polygons_path,
        depth_raster_path,
        parcels_path,
        parcel_id_field,
        scratch_gdb,
        logger,
    )
