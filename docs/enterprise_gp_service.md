# ArcGIS Enterprise geoprocessing service checklist

This is the path a Houston GIS shop uses after the Pro tool is stable. Do not
publish on the first successful desktop run.

## What you are publishing

- Toolbox: `toolboxes/FloodImpactOps.pyt`
- Tool: **2. Run flood impact**
- Execution: **asynchronous**
- Runtime: ArcGIS Server `arcgispro-py3` (default). Do not add extra pip
  packages to this project — they will not be on the server.

## Authoring rules that keep publish from breaking

1. No hardcoded `C:\Users\...` paths. All paths are tool parameters or Server
   data-store paths.
2. `arcpy.env.overwriteOutput = True` is set inside the run, not in your user
   profile.
3. Intermediate data stays in the run scratch GDB, never in a path the service
   consolidates as “project data” by accident.
4. Do not call `arcpy.mp` UI-only workflows as required steps. Map series is
   **optional**; CSV/HTML always write.
5. Derived output (`ImpactedParcels_Latest`) is set in `execute` so web clients
   can fetch a result.
6. Messages use `messages.addMessage` / `addWarningMessage` / `addErrorMessage`.
7. Timeouts: flood overlay on a full watershed is **not** a sync service.
8. REST URLs: If you pass REST URLs instead of local feature classes, the tool
   automatically paginates when record counts exceed 2000 (configurable). This
   avoids truncation while keeping data dynamic. For long-running services, ensure
   the REST endpoint is reliable and has adequate SLA.

## Data store vs copy

| Approach | Use when | Breaks when |
|---|---|---|
| **Register folder / enterprise GDB** | Parcels and FEMA live in production and refresh nightly | Server account cannot read the share; path differs from Pro |
| Copy data into the service | Tiny demo | Parcel fabric is gigabytes; every republish copies it again |

Recommendation for this app: **register** the production GDB and the AOI/flood
inputs. The GP service writes `ImpactedParcels_Latest` there (or to a dedicated
results GDB also registered). Then a Feature Service can point at `Latest`
without a second copy.

## Publish steps (Pro)

1. Open a blank Pro project. Add `FloodImpactOps.pyt`.
2. Convert sample GeoJSON with **JSON To Features**, project to 3083, save to a
   registered folder GDB.
3. Run **1. Validate flood impact inputs** — must succeed.
4. Run **2. Run flood impact** against that GDB — must succeed. This writes the
   geoprocessing **history item** the publisher needs.
5. Share → **Web Tool** (portal) or **Geoprocessing Service** (standalone Server).
6. Analyze. Fix errors about data that is not registered.
7. Set:
   - Execution: **Async**
   - Message level: **Info** during staging, **Warning** in production
   - Max records high enough for one watershed, not the whole county
8. Publish. Run the web tool once from Pro against the same inputs.
9. Point a View / Dashboard at `ImpactedParcels_Latest`.

## Environments the service honors

Set **Output Coordinate System = 3083** on the service if you want a belt-and-
suspenders guarantee. The script already projects, but operators will still
paste Web Mercator layers.

## What not to do

- Do not enable sync on a 30-minute inundation job.
- Do not return the entire history table as an in-memory feature set.
- Do not put credentials in `settings.json`.
- Do not publish from a Pro project that still points at `C:\Users\USER\...`
  scratch from development.

## Smoke tests after publish

- Empty AOI → ValidationError, job fails fast.
- Wrong geometry type (polyline flood) → fails in validate.
- Same `run_id` re-submit is not exposed on the GP service (the service mints a
  new run). Desktop CLI can pass `--run-id` to prove idempotent replace.
- Overlapping AE/floodway → unique `parcel_id` count equals impacted parcel
  count, not intersect row count.
