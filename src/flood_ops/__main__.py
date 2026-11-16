from __future__ import annotations

import argparse
import json

from .pipeline import run_flood_impact


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Houston Flood Impact Ops — run the ArcPy flood overlay workflow."
    )
    parser.add_argument("--aoi", required=True, help="AOI polygon feature class / shapefile")
    parser.add_argument("--flood", required=True, help="Flood scenario polygons")
    parser.add_argument("--parcels", required=True, help="Parcel polygons")
    parser.add_argument("--buildings", default=None, help="Optional building footprints")
    parser.add_argument("--output", required=True, help="Folder or .gdb for production outputs")
    parser.add_argument("--scratch", required=True, help="Folder for run-scoped scratch GDBs")
    parser.add_argument("--scenario", default="FEMA_SFHA")
    parser.add_argument("--aoi-name", default="AOI")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--settings", default=None)
    parser.add_argument("--aprx", default=None, help="Optional Pro project with an enabled map series")
    args = parser.parse_args()
    result = run_flood_impact(
        aoi_path=args.aoi,
        flood_path=args.flood,
        parcels_path=args.parcels,
        buildings_path=args.buildings,
        output_workspace=args.output,
        scratch_folder=args.scratch,
        scenario_name=args.scenario,
        aoi_name=args.aoi_name,
        run_id=args.run_id,
        settings_path=args.settings,
        layout_aprx=args.aprx,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "outputs"}, indent=2, default=str))
    print(json.dumps(result["outputs"], indent=2))


if __name__ == "__main__":
    main()
