# Architecture decision records

The product is configured so thresholds can move in `config/settings.json`
without renaming output fields.

## ADR-001 — What "impacted parcel" means

**Status:** **REVISED** — Cumulative 3-year flood frequency (2024-10-25)
**Decision:** A parcel is impacted when **any** of these is true:

- `cumulative_overlap_pct >= 10` (sum of overlap percentages across 3 years)
- `max_single_year_overlap_pct >= 5` (one severe event)
- `cumulative_overlap_area_sf >= 300` (sum of overlap areas across 3 years, scaled from single-year 100)

**Data source:** Three historical flood scenarios from ArcGIS REST (2016, 2017, 2018). The tool accepts three separate flood polygon inputs, runs intersect for each year, then aggregates cumulative statistics.

**Buildings:** NOT considered. The analysis focuses on land flood frequency, not existing structures. This supports vacant land assessment for future development.

**Why this and not the alternatives**

|| Rule | Use when | Breaks when |
||---|---|---|
|| Single event only | Quick reconnaissance | Misses chronic flood risk from repeated smaller events |
|| Cumulative only | Long-term risk assessment | Misses one catastrophic event that should trigger evacuation |
|| **Compound (cumulative OR single)** | **Resilience analytics** | **None — this captures both chronic and acute risk** |
|| Centroid in flood | Cheap point test | Long lots along bayous fail; legal exhibits look careless |
|| Buildings only | Structure risk / claims | Missing footprints silently under-count vacant land |

**How this fails in the future:** Someone lowers both thresholds to `0` "just to
see everything" and a dashboard starts showing 40,000 parcels. Keep the
thresholds in config, log `qc_notes` with the firing reason, and never encode
thresholds as magic numbers in SQL views.

**How to change it without breaking consumers:** Keep `impact_flag` as 0/1.
The schema now retains BOTH single-event fields (for backward compatibility) AND new cumulative fields. If the time window changes (3 years → 5 years), bump
`schema/impact_schema.json` version and add new fields — do not overwrite the
existing cumulative fields with a different meaning.

## ADR-002 — Overlay method is Vector-Raster Hybrid (Portal + local fallback)

**Status:** **REVISED** — Vector-raster hybrid with cross-sectional area (2024-10-27)
**Decision:** Use a hybrid approach for flood depth analysis:

**Primary method (Enterprise Portal):**
- Use flood polygons to select parcels that potentially intersect flood (`SelectLayerByLocation`)
- Publish depth rasters (one per year) as Image Services to ArcGIS Enterprise Portal
- Use ArcGIS API for Python (`arcgis`) to perform zonal statistics on Portal image services
- Calculate cross-sectional area (volume) = depth × area for each parcel

**Fallback method (Local, no Spatial Analyst):**
- Convert depth raster to points (each point = one raster cell with depth value)
- Use flood polygon to select points within flood extent
- Spatial Join points to parcels to aggregate depth statistics
- Calculate cross-sectional area from aggregated depth × parcel area

**Why this and not the alternatives**

|| Method | Use when | Breaks when |
||---|---|---|
|| **Vector-vector Intersect** | Simple 2D overlap | No depth information; computationally expensive for multi-year |
|| **Spatial Analyst Zonal Statistics** | Accurate depth analysis | Requires expensive Spatial Analyst license |
|| **Vector-raster hybrid (Portal)** | Enterprise-grade depth analysis | Portal unavailable or no internet |
|| **Raster-to-Points + Spatial Join** | Local fallback without license | High-resolution rasters create too many points; less accurate |

**Performance optimization:**
- Replaces 3 expensive Intersect operations with 3 zonal statistics or point-join operations
- Cumulative calculation is mathematical addition (no spatial joins across years)
- Flood polygon selection reduces the area that needs raster analysis

**Schema impact:**
- Retains 2D area fields for backward compatibility
- Adds 3D cross-sectional area fields (volume in cubic feet)
- Impact rule uses 3D thresholds: `min_cumulative_cross_sectional_area_sf: 500`, `min_single_year_cross_sectional_area_sf: 200`

**How this fails in the future:**
- A new developer "simplifies" the tool by removing the polygon selection step, causing raster analysis on the entire AOI even where no flood exists.
- Portal authentication changes or service is deprecated.
- High-resolution depth rasters create millions of points in the local fallback, causing performance issues.

## ADR-003 — CRS is EPSG 3083 (Texas Albers Equal Area) for area preservation

**Status:** **REVISED** — Texas Albers Equal Area (2024-10-28)
**Decision:** Project AOI, flood (all 3 years), depth rasters, and parcels to
NAD 1983 Texas Albers Equal Area (EPSG **3083**) before clip/intersect and
area calculations.

**Why equal-area over conformal:**

| Projection | Property | Use when | Breaks when |
|-----------|----------|----------|-------------|
| **StatePlane 2278** (conformal) | Preserves angles, distorts area | Surveying, engineering, legal boundaries | Flood impact area calculations are inaccurate |
| **Texas Albers 3083** (equal-area) | Preserves area, distorts angles | Area-based analysis, thematic mapping, impact studies | Distance/angle measurements are slightly distorted |
| **Web Mercator 3857** | Neither area nor angle preserved | Web mapping only | Any quantitative analysis is fiction |

**Why this matters for flood impact:**
- Flood impact analysis requires **accurate area measurements** (overlap sq ft, cross-sectional volume)
- Conformal projections (StatePlane) distort area, especially away from the central meridian
- Equal-area projections (Texas Albers) preserve area across the entire state
- Cross-sectional area (depth × area) is only meaningful if the area component is accurate
- The slight angle distortion in Texas Albers is acceptable for impact analysis; angle precision is not the metric

**LAEA consideration:**
Lambert Azimuthal Equal Area (LAEA) could be used for smaller study areas where depth data justifies the computational cost. For Houston-scale analysis covering multiple watersheds, Texas Albers provides better balance of area accuracy and computational efficiency.

**How this fails in the future:**
- An analyst loads a GeoJSON export (4326) and calculates `SHAPE@AREA` without projecting.
- Someone reverts to StatePlane for "compatibility" without realizing area distortion.
- Depth rasters are in a different CRS and not projected before analysis, causing volume calculation errors.

## ADR-004 — History is append-only with failure tracking; latest successful run is dashboard default

**Status:** **REVISED** — Append-only history with failure tracking (2024-10-28)
**Decision:** Write all runs to an append-only `FloodImpact_Runs` table. Never delete before write. The dashboard displays the latest successful run at the top, with full history of all runs (successful and failed) for audit trails.

**Why append-only:**

| Approach | Use when | Breaks when |
|----------|----------|-------------|
| **Delete-then-write** | Low-latency dashboards with atomic updates | Run fails mid-way → previous good data lost; no rollback |
| **Append-only** | Audit-trail critical, failure-tolerant systems | Table grows indefinitely (needs archival policy) |

**Dashboard requirements:**
- **Latest successful run** → Displayed at top as default view
- **Full run history** → All runs displayed chronologically, including failures
- **Failure summaries** → When a run fails, capture: error reason, next steps, input metadata
- **Investigation data** → All fields from impact_schema displayed for detailed post-mortem

**Run metadata captured:**
- `version_id` — Unique, traceable version identifier (e.g., git hash or semantic version)
- `run_id` — Unique run identifier (timestamp + UUID)
- `run_time_utc` — Start time
- `completion_time_utc` — End time (null if in progress)
- `status` — `IN_PROGRESS`, `SUCCEEDED`, `FAILED`
- `aoi_name`, `scenario_name` — Analysis parameters
- `input_metadata` — JSON object with: AOI path, flood paths, depth raster paths, parcel count, flood counts
- `result_summary` — JSON object with: impacted count, parcel count, cross-sectional volume (if successful)
- `failure_summary` — JSON object with: error message, error type, stack trace, next steps (if failed)

**Impact on output tables:**
- `ImpactedParcels_Latest` / `ImpactSummary_Latest` — Still replaced on successful run (dashboard default)
- `ImpactedParcels_History` / `ImpactSummary_History` — Append-only (never delete)
- `FloodImpact_Runs` — Append-only, tracks all runs with full metadata

**Why this matters for emergency ops:**
- Emergency ops uses live flood feeds during events (not this toolkit)
- This toolkit is for post-event analysis and long-term planning
- Low latency is not required; data integrity is critical
- If a run fails, dashboard must still show the previous successful run, not empty data

**Failure handling:**
- If a run fails, write a failure record to `FloodImpact_Runs` with `status=FAILED`
- Do NOT touch `Latest` tables (they retain the previous successful run)
- Do NOT write to `History` tables for the failed run
- Failure summary includes:
  - `error_type` — Validation, Analysis, Publish, etc.
  - `error_message` — Human-readable error
  - `next_steps` — Actionable guidance (e.g., "Check AOI geometry", "Verify flood raster paths")
  - `input_snapshot` — Copy of input metadata for reproduction

**How this fails in the future:**
- A developer reverts to delete-then-write for "cleaner history" and loses audit trail.
- Failure summaries are not written, making post-mortem impossible.
- `Latest` tables are overwritten on failure, breaking the dashboard default view.

## ADR-005 — Scratch vs production + structured step logging + retained spatial evidence

**Status:** **REVISED** — Structured step logging and retained spatial evidence (2024-10-28)
**Decision:** Every run gets its own scratch GDB named with `run_id`. Intermediate data dies in scratch GDB by default, but key intermediate outputs are retained as spatial evidence in a separate directory. A structured step log records execution internals for investigation.

**Structured step log:**
For each operation, record:
- Operation name (e.g., "Project to CRS", "Clip flood to AOI", "Intersect parcels × flood")
- Run ID and step ID (for traceability)
- Input dataset versions (paths, modification times)
- Analysis CRS (WKID)
- Relevant parameters (thresholds, method)
- Feature counts (input, output)
- Elapsed time
- Warnings
- Success or failure

Example log entry:
```
Intersect completed; run_id=RUN_20241028T143015Z_abc123; step_id=STP_001;
input_parcels=24,000; input_flood=3,421; output_pieces=8,506; unique_parcels=2,104;
elapsed=45s; CRS=3083; warnings=none; status=SUCCESS
```

**Retained spatial evidence:**
Keep selected intermediate outputs in a run-specific `spatial_evidence/<run_id>/` directory:
- Clipped flood extent (per year)
- Parcel-flood intersection (per year)
- Final parcel results (per year)
- Optional: pre-projected datasets for CRS verification

**Directory structure:**
```
output/
  reports/           # CSV, HTML, PDF exhibits (public dashboard)
  logs/              # Application logs (technical)
  spatial_evidence/  # Intermediate spatial outputs (investigation only)
    RUN_20241028T143015Z_abc123/
      flood_2016_clip.gdb/
      flood_2017_clip.gdb/
      flood_2018_clip.gdb/
      parcel_flood_2016_isect.gdb/
      parcel_flood_2017_isect.gdb/
      parcel_flood_2018_isect.gdb/
      parcels_final.gdb/
```

**Dashboard vs investigation:**
- Public dashboard: Shows only approved results from `Latest` tables + `History` tables
- Investigation log: Structured step log in `logs/step_log_<run_id>.json`
- Spatial evidence: Investigator loads intermediate outputs from `spatial_evidence/<run_id>/`

**Why spatial evidence matters:**
- When a run produces unexpected results, investigator needs to see intermediate states
- Clipped flood extent: Verify flood scenario was correctly clipped to AOI
- Intersection output: Verify spatial overlap is correct, not a CRS mismatch
- Final results: Compare to dashboard to confirm what was published

**Security considerations:**
- No security measures required for spatial evidence — computations on public data
- No sensitive data in step logs (just paths, counts, CRS)
- Public dashboard never exposes intermediate outputs or step logs

**Cleanup policy:**
- Scratch GDB: Deleted after run (by ops policy)
- Spatial evidence: Retained for investigation; archival policy TBD (e.g., delete after 1 year)
- Step logs: Retained for audit; archival policy TBD

**How this fails in the future:**
- A developer reverts to no spatial evidence and loses investigation capability.
- Step log is not structured, making automated analysis impossible.
- Spatial evidence grows indefinitely without archival policy.

## ADR-006 — Live REST API with pagination (records > 2000)

**Status:** **REVISED** — Live REST API with pagination (2024-10-29)
**Decision:** Query live HCFCD REST API for large datasets using pagination instead of local extracts. Use pagination when record count > 2000 to avoid truncation. Maintain duplicate copy only for small AOIs (≤2000 records) to avoid portal overhead.

**Why pagination over duplicate copy:**

| Approach | Use when | Breaks when |
|----------|----------|-------------|
| **Pagination (live REST)** | Large datasets (e.g., county-wide parcels) | Service downtime, network dependency |
| **Local extract** | Small AOIs, stable data | Data stale, manual refresh required |
| **Duplicate copy on Portal** | Small datasets with frequent access | Database infrastructure overhead, storage costs |

**Pagination threshold:** 2000 records. Below threshold, use local extract. Above threshold, use live REST with pagination.

**Implementation:**
- Query service metadata to get total record count
- If count ≤ 2000: Download as local extract (current behavior)
- If count > 2000: Use pagination with `resultRecordCount` parameter in loops
- Store paginated results in run-scoped scratch GDB for analysis
- Step log records pagination cycles and total records fetched

**Example 2018 county service:**
- Total records: 6,185
- MaxRecordCount: 2,000
- Pagination cycles: 4 (2000 + 2000 + 2000 + 185)
- Total records fetched: 6,185 (no truncation)

**Services with pagination:**
- HCFCD Parcels: HCAD county-wide parcels (use pagination for AOI > 2000 parcels)
- HCFCD FEMA: Flood hazard zones (may exceed 2000 features)
- HCFCD Channels: Drainage infrastructure (may exceed 2000 features)

**Risk mitigation:**
- Step log records number of pagination cycles
- Validate total records fetched against expected count
- Timeout handling for slow pagination cycles
- Cache result offset to resume if service times out

**How this fails in the future:**
- A developer hardcodes MaxRecordCount = 2000 without pagination logic → truncation on large datasets.
- Service changes pagination parameter name → tool breaks (use ArcGIS REST API spec for parameter name detection).
- Service changes MaxRecordCount → adjust threshold in config.

## ADR-007 — GP service is async; register the data store

**Status:** Accepted as the publish recommendation
See [enterprise_gp_service.md](enterprise_gp_service.md).
