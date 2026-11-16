# Dashboard Requirements

This document specifies the data structure and behavior for the Houston Flood Impact Ops dashboard.

## Dashboard Views

### 1. Latest Successful Run (Default View)

**Purpose:** Display the most recent successful analysis as the default dashboard view.

**Data Source:** `ImpactedParcels_Latest` + `ImpactSummary_Latest`

**Display Requirements:**
- Map view of impacted parcels (styled by impact severity)
- Summary statistics at top:
  - Total parcels in AOI
  - Impacted parcels count and percentage
  - Total cross-sectional flood volume (cubic feet)
  - Total 2D overlap area (sq ft)
- Run metadata displayed in sidebar:
  - Run ID
  - Run time (UTC)
  - Scenario name
  - AOI name
  - Version ID (git hash or semantic version)
- Filter by impact flag (impacted vs not impacted)
- Filter by flood zone
- Sort by cross-sectional area (descending) to identify worst-affected parcels

**Behavior:**
- Always shows the latest run with `status=SUCCEEDED`
- If no successful runs exist, show empty state with message "No successful runs yet"
- If the most recent run failed, do NOT switch to it — keep showing the previous successful run

---

### 2. Full Run History

**Purpose:** Display all runs (successful and failed) in chronological order for audit trail.

**Data Source:** `FloodImpact_Runs` table

**Display Requirements:**
- Table view with columns:
  - Run ID (clickable to view details)
  - Version ID
  - Run time (UTC)
  - Completion time (UTC)
  - Status (IN_PROGRESS, SUCCEEDED, FAILED)
  - Scenario name
  - AOI name
  - Input metadata count (expandable)
  - Result summary (if SUCCEEDED, expandable)
  - Failure summary (if FAILED, expandable)

**Color Coding:**
- SUCCEEDED: Green
- FAILED: Red
- IN_PROGRESS: Yellow

**Click Actions:**
- Click run ID → Open detailed view of that run's results
- Click input metadata → Expand to show:
  - AOI path
  - Flood paths (all 3 years)
  - Depth raster paths (all 3 years)
  - Parcel path
  - Feature counts
  - CRS used
- Click failure summary → Expand to show:
  - Error type
  - Error message
  - Next steps (actionable guidance)
  - Stack trace (collapsible)

---

### 3. Run Detail View

**Purpose:** Detailed investigation of a specific run.

**Data Source:** `ImpactedParcels_History` (filtered by run_id) + `ImpactSummary_History` (filtered by run_id)

**Display Requirements:**
- Header section:
  - Run ID, Version ID, Run time, Completion time, Status
  - Scenario name, AOI name
  - All fields from `FloodImpact_Runs` for that run
- Map view of impacted parcels for that run
- Data table with all fields from `ImpactedParcels_History`:
  - Parcel ID
  - Flood zone(s)
  - Parcel area (sq ft)
  - 2D overlap stats (area, %, cumulative)
  - 3D cross-sectional stats (volume, cumulative, max single year)
  - Years with flood count
  - Impact flag
  - Impact rule
  - QC notes
- Export options:
  - CSV export of parcel table
  - PDF map export (if layout available)

---

## Data Model Reference

### FloodImpact_Runs Table Fields

| Field | Type | Description | Dashboard Use |
|-------|------|-------------|---------------|
| run_id | TEXT (64) | Unique run identifier | Primary key, clickable |
| version_id | TEXT (64) | Git hash or semantic version | Traceability, reproducibility |
| run_time_utc | DATE | Start time | Sort order, time filter |
| completion_time_utc | DATE | End time | Duration calculation |
| status | TEXT (32) | IN_PROGRESS, SUCCEEDED, FAILED | Color coding, filter |
| scenario_name | TEXT (128) | Analysis scenario | Filter, grouping |
| aoi_name | TEXT (128) | Area of interest name | Filter, grouping |
| input_metadata | TEXT (2000) | JSON object with input paths | Expandable details |
| result_summary | TEXT (2000) | JSON object with results (if SUCCEEDED) | Expandable summary |
| failure_summary | TEXT (2000) | JSON object with error info (if FAILED) | Expandable next steps |

### input_metadata JSON Structure

```json
{
  "aoi_path": "/path/to/aoi.gdb/aoi",
  "flood_paths": ["/path/to/flood_2016.gdb/flood", "/path/to/flood_2017.gdb/flood", "/path/to/flood_2018.gdb/flood"],
  "depth_raster_paths": ["/path/to/depth_2016.tif", "/path/to/depth_2017.tif", "/path/to/depth_2018.tif"],
  "parcels_path": "/path/to/parcels.gdb/parcels",
  "buildings_path": "/path/to/buildings.gdb/buildings",
  "overlay_method": "vector_raster_hybrid",
  "crs_wkid": 3083,
  "aoi_count": 1,
  "flood_counts": {"2016": 150, "2017": 142, "2018": 160},
  "parcel_count": 24000,
  "building_count": 8000
}
```

### result_summary JSON Structure (SUCCEEDED)

```json
{
  "impacted_count": 1250,
  "parcel_count": 24000,
  "impacted_cross_sectional_area_sf": 450000.0
}
```

### failure_summary JSON Structure (FAILED)

```json
{
  "error_type": "VALIDATION",
  "error_message": "AOI has 0 features",
  "next_steps": [
    "Check AOI geometry (must be polygon)",
    "Verify AOI path is correct",
    "Ensure AOI has at least one feature"
  ],
  "stack_trace": "Traceback (most recent call last)..."
}
```

---

## Dashboard Behavior Specifications

### 1. Failure Recovery

**Scenario:** A run fails mid-way (e.g., during intersect operation).

**Behavior:**
- `FloodImpact_Runs` gets a row with `status=FAILED` and failure summary
- `ImpactedParcels_Latest` and `ImpactSummary_Latest` are NOT touched (retain previous successful run)
- `ImpactedParcels_History` and `ImpactSummary_History` do NOT get data for the failed run
- Dashboard continues showing the previous successful run as default
- Full history shows the failed run with red color and expandable failure summary

**Next Steps Display:**
- For validation failures: "Check AOI geometry, verify flood scenarios, ensure parcels have required ID field"
- For execution failures: "Check ArcPy environment, verify input paths, review logs, ensure disk space"
- For publish failures: "Check production GDB permissions, verify schema compatibility"

### 2. In-Progress Runs

**Scenario:** A run is currently executing.

**Behavior:**
- `FloodImpact_Runs` gets a row with `status=IN_PROGRESS` when run starts
- Dashboard shows this run in history table with yellow color
- Default view continues showing previous successful run
- When run completes, row is updated to SUCCEEDED or FAILED

### 3. Reproducibility

**Scenario:** Investigator needs to reproduce a specific run.

**Behavior:**
- Click on run ID in history to view detailed run
- Expand input metadata to see exact paths used
- Expand result summary to see exact counts
- Use version_id to check out specific code version (if using git)
- Re-run with exact same inputs (if data still exists)

### 4. Archival Policy

**Scenario:** Runs table grows indefinitely over years.

**Behavior:**
- Dashboard should implement an archival policy (outside this tool):
  - Archive runs older than 1 year to a separate table
  - Keep summary of archived runs in a lightweight table
  - Provide "Load Archived" button for historical investigation
- This is a dashboard consideration, not a tool requirement

---

## Dashboard SQL Queries (Reference)

### Latest Successful Run

```sql
SELECT *
FROM FloodImpact_Runs
WHERE status = 'SUCCEEDED'
ORDER BY run_time_utc DESC
LIMIT 1
```

### Failed Runs Only

```sql
SELECT run_id, run_time_utc, status, failure_summary
FROM FloodImpact_Runs
WHERE status = 'FAILED'
ORDER BY run_time_utc DESC
```

### Run with Specific Impact Thresholds

```sql
SELECT COUNT(*) as impacted_count
FROM ImpactedParcels_History
WHERE run_id = '<run_id>'
  AND impact_flag = 1
  AND cumulative_cross_sectional_area_sf >= 500
```

### Step Log for a Specific Run

Step logs are stored in `logs/step_log_<run_id>.json`. Query structure:

```json
{
  "run_id": "RUN_20241028T143015Z_abc123",
  "total_steps": 5,
  "successful_steps": 5,
  "failed_steps": 0,
  "steps": [
    {
      "step_id": "STP_001",
      "step_name": "Project inputs to client CRS",
      "start_time_utc": "2024-10-28T14:30:15Z",
      "end_time_utc": "2024-10-28T14:30:20Z",
      "elapsed_seconds": 5.2,
      "crs_wkid": 3083,
      "feature_counts": {"parcels_clip": 24000},
      "status": "SUCCESS"
    },
    ...
  ]
}
```

---

## Investigation Workflow

When a run produces unexpected results, an investigator should:

1. **Check the step log:**
   - Open `logs/step_log_<run_id>.json`
   - Review each step's status, elapsed time, and feature counts
   - Identify which step failed or took unexpectedly long

2. **Load spatial evidence:**
   - Navigate to `spatial_evidence/<run_id>/`
   - Load clipped flood extent to verify flood scenario was correctly clipped
   - Load parcel-flood intersection to verify spatial overlap
   - Compare with final results to confirm what was published

3. **Reproduce the run:**
   - Copy input paths from the run's `input_metadata`
   - Use the same version_id (git checkout or note schema version)
   - Re-run with exact same inputs
   - Compare step log and spatial evidence to original run

## Archival Policy (Dashboard, Not Tool)

The tool writes all data. The dashboard should implement archival:

- Step logs: Archive after 6 months, keep summary index
- Spatial evidence: Archive after 1 year, delete intermediate GDBs
- FloodImpact_Runs: Keep indefinitely for audit (it's a small table)

## Implementation Notes

**The tool writes all data. The dashboard consumes it.**

This document describes dashboard requirements, not dashboard implementation. The tool provides:
- Append-only `FloodImpact_Runs` table with full metadata
- History tables with all run data
- Latest tables with most recent successful run
- Failure summaries with actionable next steps
- Structured step logs in `logs/step_log_<run_id>.json`
- Spatial evidence in `spatial_evidence/<run_id>/` for investigation

Dashboard developers should:
- Use the SQL queries above as reference
- Implement the expandable metadata/failure summary UI
- Color-code by status
- Keep default view on latest successful run
- Provide export functionality from detail views
- Add "View Step Log" button to run detail view
- Add "Load Spatial Evidence" button for investigation
