from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def apply_impact_rule(
    cumulative_overlap_pct: float,
    max_single_year_overlap_pct: float,
    cumulative_overlap_area_sf: float,
    cumulative_cross_sectional_area_sf: float,
    max_single_year_cross_sectional_area_sf: float,
    settings: dict[str, Any],
) -> tuple[int, str]:
    """Return (impact_flag, qc_note). Pure function — unit-test this, not ArcPy."""
    rule = settings["impact_rule"]
    min_cumulative_pct = float(rule["min_cumulative_overlap_pct"])
    min_single_pct = float(rule["min_single_year_overlap_pct"])
    min_cumulative_area = float(rule["min_cumulative_overlap_area_sf"])
    min_cumulative_cross_sectional = float(rule["min_cumulative_cross_sectional_area_sf"])
    min_single_cross_sectional = float(rule["min_single_year_cross_sectional_area_sf"])

    reasons: list[str] = []
    if cumulative_cross_sectional_area_sf >= min_cumulative_cross_sectional:
        reasons.append(f"cumulative_cross_sectional_area_sf>={min_cumulative_cross_sectional}")
    if max_single_year_cross_sectional_area_sf >= min_single_cross_sectional:
        reasons.append(f"max_single_year_cross_sectional_area_sf>={min_single_cross_sectional}")
    if cumulative_overlap_pct >= min_cumulative_pct:
        reasons.append(f"cumulative_overlap_pct>={min_cumulative_pct}")
    if max_single_year_overlap_pct >= min_single_pct:
        reasons.append(f"max_single_year_overlap_pct>={min_single_pct}")
    if cumulative_overlap_area_sf >= min_cumulative_area:
        reasons.append(f"cumulative_overlap_area_sf>={min_cumulative_area}")

    if reasons:
        return 1, ";".join(reasons)
    return 0, "below_threshold"


def collapse_parcel_overlaps(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse multi-year intersect rows to one row per parcel with cumulative statistics.

    For 3-year cumulative analysis, each parcel may have multiple intersect rows (one per year per flood zone).
    This function aggregates:
    - cumulative_overlap_area_sf: sum of overlap areas across all years (2D)
    - cumulative_overlap_pct: sum of overlap percentages across all years (2D)
    - cumulative_cross_sectional_area_sf: sum of cross-sectional areas across all years (3D volume)
    - max_single_year_overlap_pct: maximum overlap percentage in any single year (2D)
    - max_single_year_cross_sectional_area_sf: maximum cross-sectional area in any single year (3D)
    - years_with_flood_count: number of years (out of 3) with any overlap
    - overlap_area_sf, overlap_pct: retained as the maximum single-year values (for backward compatibility)
    """
    grouped: dict[str, dict[str, Any]] = {}
    zones: dict[str, set[str]] = defaultdict(set)
    years_per_parcel: dict[str, set[int]] = defaultdict(set)

    for row in rows:
        parcel_id = str(row["parcel_id"])
        year = int(row.get("year", 0))
        if parcel_id not in grouped:
            grouped[parcel_id] = {
                "parcel_id": parcel_id,
                "parcel_area_sf": float(row["parcel_area_sf"]),
                "cumulative_overlap_area_sf": 0.0,
                "max_single_year_overlap_area_sf": 0.0,
                "max_single_year_overlap_pct": 0.0,
                "cumulative_cross_sectional_area_sf": 0.0,
                "max_single_year_cross_sectional_area_sf": 0.0,
                "building_count": 0,
                "aoi_name": row.get("aoi_name") or "",
            }
        overlap_area = float(row["overlap_area_sf"])
        overlap_pct = float(row.get("overlap_pct", 0.0))
        cross_sectional_area = float(row.get("cross_sectional_area_sf", 0.0))
        grouped[parcel_id]["cumulative_overlap_area_sf"] += overlap_area
        grouped[parcel_id]["max_single_year_overlap_area_sf"] = max(
            grouped[parcel_id]["max_single_year_overlap_area_sf"], overlap_area
        )
        grouped[parcel_id]["max_single_year_overlap_pct"] = max(
            grouped[parcel_id]["max_single_year_overlap_pct"], overlap_pct
        )
        grouped[parcel_id]["cumulative_cross_sectional_area_sf"] += cross_sectional_area
        grouped[parcel_id]["max_single_year_cross_sectional_area_sf"] = max(
            grouped[parcel_id]["max_single_year_cross_sectional_area_sf"], cross_sectional_area
        )
        if year > 0:
            years_per_parcel[parcel_id].add(year)
        zone = (row.get("flood_zone") or "").strip()
        if zone:
            zones[parcel_id].add(zone)

    collapsed: list[dict[str, Any]] = []
    for parcel_id, item in grouped.items():
        parcel_area = item["parcel_area_sf"] if item["parcel_area_sf"] else 0.0
        cumulative_overlap = item["cumulative_overlap_area_sf"]
        # Cumulative overlap can theoretically exceed parcel area when flood zones overlap across years.
        if parcel_area > 0 and cumulative_overlap > parcel_area:
            cumulative_overlap = parcel_area
            item["overlap_capped"] = True
        else:
            item["overlap_capped"] = False
        cumulative_overlap_pct = (cumulative_overlap / parcel_area * 100.0) if parcel_area > 0 else 0.0
        item["cumulative_overlap_area_sf"] = cumulative_overlap
        item["cumulative_overlap_pct"] = cumulative_overlap_pct
        # Retain single-year fields as max values for backward compatibility
        item["overlap_area_sf"] = item["max_single_year_overlap_area_sf"]
        item["overlap_pct"] = item["max_single_year_overlap_pct"]
        item["cross_sectional_area_sf"] = item["max_single_year_cross_sectional_area_sf"]
        item["years_with_flood_count"] = len(years_per_parcel.get(parcel_id, set()))
        item["flood_zone"] = "|".join(sorted(zones[parcel_id]))
        collapsed.append(item)
    return collapsed
