from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .workspace import RunContext


def write_reports(
    arcpy,
    settings: dict[str, Any],
    ctx: RunContext,
    overlay: dict[str, Any],
    outputs: dict[str, str],
    layout_aprx: str | None,
    logger,
) -> dict[str, str]:
    reports: dict[str, str] = {}
    csv_path = ctx.output_dir / f"{ctx.run_id}_impacted_parcels.csv"
    write_csv(csv_path, overlay["collapsed"], ctx)
    reports["csv"] = str(csv_path)

    html_path = ctx.output_dir / f"{ctx.run_id}_summary.html"
    write_html(html_path, overlay, ctx, settings)
    reports["html"] = str(html_path)

    if layout_aprx and settings["reporting"].get("map_series_enabled"):
        try:
            pdf_path = export_map_series(arcpy, layout_aprx, ctx, logger)
            if pdf_path:
                reports["pdf"] = pdf_path
        except Exception as exc:
            logger.warning("Map series export skipped: %s", exc)
    else:
        logger.info("Map series skipped (no .aprx layout provided). CSV/HTML still written.")
    logger.info("Reports written: %s", ", ".join(reports))
    return reports


def write_csv(path: Path, rows: list[dict[str, Any]], ctx: RunContext) -> None:
    fieldnames = [
        "run_id",
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
        "years_with_flood_count",
        "impact_flag",
        "building_count",
        "qc_notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (-r["impact_flag"], -r["cumulative_overlap_pct"])):
            writer.writerow(
                {
                    "run_id": ctx.run_id,
                    "scenario_name": ctx.scenario_name,
                    "aoi_name": ctx.aoi_name,
                    "parcel_id": row["parcel_id"],
                    "flood_zone": row.get("flood_zone", ""),
                    "parcel_area_sf": f"{row['parcel_area_sf']:.2f}",
                    "overlap_area_sf": f"{row['overlap_area_sf']:.2f}",
                    "overlap_pct": f"{row['overlap_pct']:.2f}",
                    "cumulative_overlap_area_sf": f"{row['cumulative_overlap_area_sf']:.2f}",
                    "cumulative_overlap_pct": f"{row['cumulative_overlap_pct']:.2f}",
                    "max_single_year_overlap_pct": f"{row['max_single_year_overlap_pct']:.2f}",
                    "years_with_flood_count": row.get("years_with_flood_count", 0),
                    "impact_flag": row["impact_flag"],
                    "building_count": row.get("building_count", 0),
                    "qc_notes": row.get("qc_notes", ""),
                }
            )


def write_html(path: Path, overlay: dict[str, Any], ctx: RunContext, settings: dict[str, Any]) -> None:
    impacted = overlay["impacted_rows"]
    top_n = int(settings["reporting"]["top_n_parcels"])
    top = sorted(impacted, key=lambda r: r["cumulative_overlap_pct"], reverse=True)[:top_n]
    rows_html = "\n".join(
        f"<tr><td>{r['parcel_id']}</td><td>{r.get('flood_zone','')}</td>"
        f"<td>{r['cumulative_overlap_pct']:.1f}</td><td>{r['cumulative_overlap_area_sf']:.0f}</td>"
        f"<td>{r['max_single_year_overlap_pct']:.1f}</td><td>{r.get('years_with_flood_count',0)}</td>"
        f"<td>{r.get('qc_notes','')}</td></tr>"
        for r in top
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Flood impact {ctx.run_id}</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; }}
th {{ background: #0b3d91; color: white; }}
</style></head><body>
<h1>Houston Flood Impact Ops</h1>
<p><strong>Run:</strong> {ctx.run_id}<br>
<strong>Scenario:</strong> {ctx.scenario_name}<br>
<strong>AOI:</strong> {ctx.aoi_name}<br>
<strong>Parcels in AOI:</strong> {overlay['aoi_parcel_count']}<br>
<strong>Impacted parcels:</strong> {len(impacted)}</p>
<h2>Top {top_n} impacted parcels (by cumulative overlap)</h2>
<table>
<thead><tr><th>Parcel ID</th><th>Flood zone</th><th>Cumulative %</th><th>Cumulative sq ft</th><th>Max single %</th><th>Years flooded</th><th>QC</th></tr></thead>
<tbody>
{rows_html}
</tbody></table>
<p>This HTML exhibit is the fallback when no Pro layout is attached. Operators attach an .aprx to export Map Series PDFs.</p>
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def export_map_series(arcpy, aprx_path: str, ctx: RunContext, logger) -> str | None:
    """Export the first map series layout in a Pro project. Requires an authored .aprx."""
    aprx = arcpy.mp.ArcGISProject(aprx_path)
    for layout in aprx.listLayouts():
        if layout.mapSeries and layout.mapSeries.enabled:
            pdf_path = str(ctx.output_dir / f"{ctx.run_id}_map_series.pdf")
            layout.mapSeries.exportToPDF(pdf_path)
            logger.info("Exported map series PDF: %s", pdf_path)
            return pdf_path
    logger.warning("APRX has no enabled map series layout: %s", aprx_path)
    return None
