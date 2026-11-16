# Houston Flood Impact Ops

**ArcPy** geoprocessing application for Harris County flood impact:
Clip a watershed (or incident polygon) to a flood scenario, overlay parcels and
optional buildings, write a **schema-stable** geodatabase, and emit CSV/HTML
exhibits that can be published as an ArcGIS Enterprise GP service.

This is a workflow GIS Applications (flood control, local government,
Esri partners) automate. The overlay tools are ordinary. The product
survives because of **CRS, schema, scratch vs production, run history, and
fail-fast validation**.

## What the tool does

1. Validate AOI, flood, parcels (and optional buildings): polygon, counts, ID fields.
2. For REST URLs, use automatic pagination when record counts exceed 2000 ([ADR-006](docs/decisions.md)).
3. Project everything to **EPSG 3083 (Texas Albers Equal Area)** for area-accurate calculations.
4. Clip flood and parcels to the AOI.
5. Intersect; collapse overlapping flood zones to **one row per parcel**.
6. Flag impact using overlap % / area / building hits ([ADR-001](docs/decisions.md)).
7. Write `ImpactedParcels_History` + `_Latest` and matching summary tables.
8. Write `{run_id}_impacted_parcels.csv` and a summary HTML. Map Series PDF if you
   pass a Pro project with an enabled series.

## Repository layout

```text
config/settings.json          # CRS, impact thresholds, QC guardrails
schema/impact_schema.json     # output field contract
src/flood_ops/                # testable Python package
toolboxes/FloodImpactOps.pyt  # thin ArcGIS Pro / Server UI
data/sample/geojson/          # one-watershed sample pack
docs/                         # ADRs, GP service checklist, client staffing
tests/                        # rules + config tests; optional ArcPy integration
```

## Requirements

- ArcGIS Pro or ArcGIS Server Python (`arcgispro-py3`) with **ArcPy**
- No extra pip packages (so the GP service stays publishable)

## Quick start in ArcGIS Pro

1. Clone / copy this folder onto a machine with Pro.
2. Run `python scripts/build_sample_data.py` with Pro’s Python if you want a
   file GDB. Otherwise use **JSON To Features** on `data/sample/geojson/*.geojson`
   and **Project** to 3083 (Texas Albers Equal Area).
3. In Pro: Catalog → Toolboxes → add `toolboxes/FloodImpactOps.pyt`.
4. Run **1. Validate flood impact inputs**.
5. Run **2. Run flood impact**. Set production workspace to a folder you own and
   scratch to a disposable folder.

## CLI (same engine as the toolbox)

```text
"%PROGRAMFILES%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" -m flood_ops ^
  --aoi <aoi_fc> --flood <flood_fc> --parcels <parcels_fc> ^
  --buildings <buildings_fc> --output <folder_or.gdb> --scratch <scratch_folder> ^
  --scenario FEMA_SFHA --aoi-name "Brays Bayou"
```

Set `PYTHONPATH` to `src` or run from a Pro conda env after `pip install -e .`
is **not** required; use `PYTHONPATH=src`.

## Tests that do not need ArcPy

```text
python -m unittest discover -s tests -v
```

`test_arcpy_integration.py` skips unless ArcPy is importable.

## Public data this sample is modeled on

HCFCD REST catalog: [https://www.gis.hctx.net/arcgishcpid/rest/services/HCFCD](https://www.gis.hctx.net/arcgishcpid/rest/services/HCFCD)

You can live-query REST URLs from the tool with automatic pagination when record counts exceed 2000. See ADR-006 for details.

## Enterprise publish

Read [`docs/enterprise_gp_service.md`](docs/enterprise_gp_service.md) before you
click Share. Async. Register the data store. Do not copy the parcel fabric into
the service.

## Schema change policy

If a dashboard or Feature Service consumes `overlap_pct`, you do not rename that
field on a Friday. Bump `schema/impact_schema.json` `version`, migrate, and
release together.
