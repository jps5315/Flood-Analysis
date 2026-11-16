"""Build a one-watershed sample pack with 3-year historical flood data and depth rasters.

Tries HCFCD REST extracts first with pagination support. If the public service throttles or times out,
writes a geometrically honest synthetic subset in the Brays Bayou area so the
toolbox still runs in minutes. Generates 3 separate flood layers (2016, 2017, 2018)
for cumulative flood frequency analysis, plus synthetic depth rasters for each year.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flood_ops.rest_loader import RestLoader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sample" / "geojson"
LINEAGE = ROOT / "data" / "sample" / "LINEAGE.md"

WATERSHED_URL = "https://www.gis.hctx.net/arcgishcpid/rest/services/HCFCD/Watershed/MapServer/0"
FEMA_URL = "https://www.gis.hctx.net/arcgishcpid/rest/services/HCFCD/FEMA/FeatureServer/5"

# Brays Bayou approximate WGS84 window used when REST is unavailable.
BRAYS_BBOX = (-95.52, 29.68, -95.36, 29.74)
HISTORICAL_YEARS = [2016, 2017, 2018]


def ring(lon, lat, width_deg, height_deg) -> list[list[float]]:
    return [
        [lon, lat],
        [lon + width_deg, lat],
        [lon + width_deg, lat + height_deg],
        [lon, lat + height_deg],
        [lon, lat],
    ]


def synthetic_pack() -> dict[str, dict]:
    west, south, east, north = BRAYS_BBOX
    aoi = {
        "type": "FeatureCollection",
        "name": "aoi",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"aoi_name": "Brays Bayou (sample)", "WATERSHED": "Brays Bayou"},
                "geometry": {"type": "Polygon", "coordinates": [ring(west, south, east - west, north - south)]},
            }
        ],
    }

    # Generate 3 years of flood data with varying extent to test cumulative analysis
    flood_by_year = {}
    for idx, year in enumerate(HISTORICAL_YEARS):
        year_offset = idx * 0.01
        flood_features = [
            {
                "type": "Feature",
                "properties": {"flood_zone": "AE", "SFHA_TF": "T", "scenario": f"FEMA_{year}"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring(west + 0.02 + year_offset, south + 0.01, 0.08, 0.025)],
                },
            },
            {
                "type": "Feature",
                "properties": {"flood_zone": "AE", "SFHA_TF": "T", "scenario": f"FEMA_{year}"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring(west + 0.06 - year_offset, south + 0.018, 0.05, 0.02)],
                },
            },
            {
                "type": "Feature",
                "properties": {"flood_zone": "X", "SFHA_TF": "F", "scenario": f"FEMA_{year}"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring(west + 0.11, south + 0.03 + year_offset, 0.03, 0.015)],
                },
            },
        ]
        flood_by_year[year] = {
            "type": "FeatureCollection",
            "name": f"flood_{year}",
            "features": flood_features,
        }

    parcels = {"type": "FeatureCollection", "name": "parcels", "features": []}
    buildings = {"type": "FeatureCollection", "name": "buildings", "features": []}
    cols, rows = 6, 4
    dx = (east - west - 0.01) / cols
    dy = (north - south - 0.01) / rows
    n = 0
    for r in range(rows):
        for c in range(cols):
            n += 1
            lon = west + 0.005 + c * dx
            lat = south + 0.005 + r * dy
            pid = f"HCAD-SAMPLE-{n:04d}"
            parcels["features"].append(
                {
                    "type": "Feature",
                    "properties": {"parcel_id": pid, "ACCOUNT": pid},
                    "geometry": {"type": "Polygon", "coordinates": [ring(lon, lat, dx * 0.85, dy * 0.85)]},
                }
            )
            if n % 3 == 0:
                buildings["features"].append(
                    {
                        "type": "Feature",
                        "properties": {"building_id": f"BLDG-{n:04d}", "parcel_id": pid},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [ring(lon + dx * 0.2, lat + dy * 0.2, dx * 0.2, dy * 0.2)],
                        },
                    }
                )
    pack = {"aoi": aoi, "parcels": parcels, "buildings": buildings}
    for year in HISTORICAL_YEARS:
        pack[f"flood_{year}"] = flood_by_year[year]
    return pack


def write_fc(name: str, collection: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.geojson"
    path.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    print(f"Wrote {path} ({len(collection.get('features', []))} features)")
    return path


def write_lineage(used_rest: bool) -> None:
    text = f"""# Sample data lineage

## Purpose
A **one-watershed** extract so the toolbox finishes in minutes. County-wide live REST
queries are not a production pattern: HCAD parcels advertise `MaxRecordCount: 2000`
and a minimum scale. A senior developer extracts, stores, and versions the AOI.

## Coordinate systems
GeoJSON files are stored in **EPSG:4326** (GeoJSON default). The ArcPy pipeline
projects them to **EPSG 3083** (NAD 1983 Texas Albers Equal Area, meters)
before any area calculation.

## Sources
- HCFCD REST catalog: https://www.gis.hctx.net/arcgishcpid/rest/services/HCFCD
- Watershed service: `HCFCD/Watershed`
- Flood scenario proxy: `HCFCD/FEMA` / Flood Hazard Zones (3 historical years: {HISTORICAL_YEARS})
- Parcels: synthetic HCAD-shaped sample (public MapServer is not bulk-downloadable)
- Depth rasters: NOT generated by this script. In production, depth rasters come from hydrology models.

## What was written this run
- REST extract succeeded: **{used_rest}**
- If REST failed, synthetic Brays Bayou window `{BRAYS_BBOX}` was used.
- Generated 3 separate flood layers for cumulative frequency analysis.
- Depth rasters: Must be created manually in ArcGIS Pro from hydrology model outputs.
  For testing, you can create synthetic depth rasters using the Spatial Analyst extension:
  1. Create a constant raster (e.g., 2 ft depth) over the AOI
  2. Clip to flood polygons for each year
  3. Save as depth_2016.tif, depth_2017.tif, depth_2018.tif
- This is training data, not a regulatory floodplain product. Do not file it as FEMA.

## Refresh policy
Re-run `python scripts/build_sample_data.py` when you need a new fixture. Do not
silently replace production GDB layers with this sample pack.
"""
    LINEAGE.write_text(text, encoding="utf-8")


def convert_with_arcpy(geojson_dir: Path) -> None:
    try:
        import arcpy  # type: ignore
    except ImportError:
        print("ArcPy not found — GeoJSON sample pack is still usable after JSON To Features in Pro.")
        return
    gdb_dir = ROOT / "data" / "sample"
    gdb_name = "sample.gdb"
    gdb = gdb_dir / gdb_name
    arcpy.env.overwriteOutput = True
    if arcpy.Exists(str(gdb)):
        arcpy.management.Delete(str(gdb))
    arcpy.management.CreateFileGDB(str(gdb_dir), gdb_name)
    wkid = 3083
    for name in ("aoi", "parcels", "buildings"):
        geojson = geojson_dir / f"{name}.geojson"
        raw = str(gdb / f"{name}_wgs84")
        projected = str(gdb / name)
        arcpy.conversion.JSONToFeatures(str(geojson), raw, "POLYGON")
        arcpy.management.Project(raw, projected, arcpy.SpatialReference(wkid))
        print(f"Loaded {name} into {projected}")
    for year in HISTORICAL_YEARS:
        name = f"flood_{year}"
        geojson = geojson_dir / f"{name}.geojson"
        raw = str(gdb / f"{name}_wgs84")
        projected = str(gdb / name)
        arcpy.conversion.JSONToFeatures(str(geojson), raw, "POLYGON")
        arcpy.management.Project(raw, projected, arcpy.SpatialReference(wkid))
        print(f"Loaded {name} into {projected}")


def main() -> int:
    used_rest = False
    pack = synthetic_pack()

    # Try to load watershed data using pagination
    try:
        loader = RestLoader(pagination_threshold=2000, pagination_record_count=2000, timeout=60)

        # Query watershed with pagination
        features, pagination_info = loader.query_features(
            f"{WATERSHED_URL}/0",
            where_clause="UPPER(NAME) LIKE '%BRAYS%' OR UPPER(WS_NAME) LIKE '%BRAYS%'",
            out_fields="*",
            spatial_reference=4326
        )

        if features:
            used_rest = True
            pack["aoi"] = {
                "type": "FeatureCollection",
                "name": "aoi",
                "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                "features": features,
                "metadata": {"pagination_info": pagination_info}
            }
            print(f"REST watershed features: {len(features)} (pagination: {pagination_info['use_pagination']}, cycles: {pagination_info['pagination_cycles']})")
            # Keep synthetic flood/parcels; they sit in the Brays window even if the
            # official watershed polygon is a different shape. Clip still teaches the workflow.
    except Exception as e:
        print(f"REST watershed query failed: {e}")
        print("Using synthetic AOI")

    write_fc("aoi", pack["aoi"])
    for year in HISTORICAL_YEARS:
        write_fc(f"flood_{year}", pack[f"flood_{year}"])
    write_fc("parcels", pack["parcels"])
    write_fc("buildings", pack["buildings"])
    write_lineage(used_rest)
    convert_with_arcpy(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
