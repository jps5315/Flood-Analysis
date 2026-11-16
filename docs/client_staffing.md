## Problem statement

After a flood event (or for SFHA baseline planning), operations needs a
**repeatable, defensible** answer to: which parcels and structures in this
watershed are inundated, by how much, and what did we publish at time T?

That is the same pattern as permit screening, pipeline ROW impact, and outage
impact. The overlay is not the hard part. The contract is.

## Assumptions

- Authoritative parcels (HCAD or the city’s cadastral GDB), not a web export.
- Flood scenario owner: HCFCD FEMA SFHA vs. an event inundation polygon/raster
  from hydrology. This app speaks **polygons**. Rasters are a phase-2 zonal
  statistic, not a silent `RasterToPolygon` in the same tool.
- CRS 3083 (Texas Albers Equal Area). Area in square meters (converted to sq ft for output).
- “Impacted” is a **business rule** signed by emergency management / floodplain
  admin, not by the GIS developer alone.
- Buildings may be missing. The tool still runs; `building_count` is 0.

## What we deliver

1. Python Toolbox + this repository.
2. Schema contract (`schema/impact_schema.json`) consumed by the Feature Service
   and any Dashboard.
3. History + latest feature classes in a registered GDB.
4. Async GP service.
5. CSV/HTML exhibits; Map Series PDF only if they already have a layout
   standard.
6. QC gates and a run log per `run_id`.

## What we do not deliver in v1

Utility Network, live gauges, a custom JS web app, or county-wide unclipped
intersects. Those consume this service.

## Change control (this is how products survive)

- Field rename = schema version bump + migration script + dashboard update in
  the same release.
- Threshold change = config + ADR note + screenshot of before/after counts.
- New flood source (raster) = new tool, not a hidden branch in this one.

## Risks

- Live REST truncation (MaxRecordCount).
- Overlapping FEMA polygons double-counting parcels.
- Publishing scratch layers.
- Overwriting the only copy of last night’s run.
- Calculating area in 4326 or 3857.

