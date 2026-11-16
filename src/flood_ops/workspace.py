from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class RunContext:
    run_id: str
    run_time_utc: datetime
    scratch_gdb: str
    production_gdb: str
    output_dir: Path
    log_dir: Path
    spatial_evidence_dir: Path
    scenario_name: str
    aoi_name: str


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"RUN_{stamp}_{uuid.uuid4().hex[:8]}"


def prepare_run(
    arcpy,
    settings: dict[str, Any],
    output_workspace: str,
    scratch_folder: str,
    scenario_name: str,
    aoi_name: str,
    run_id: str | None = None,
) -> RunContext:
    """Create scratch + production GDBs. Intermediate data never lands in production."""
    run_id = run_id or new_run_id()
    run_time = datetime.now(timezone.utc)
    scratch_root = Path(scratch_folder)
    scratch_root.mkdir(parents=True, exist_ok=True)
    scratch_gdb = str(scratch_root / f"{run_id}.gdb")
    if arcpy.Exists(scratch_gdb):
        arcpy.management.Delete(scratch_gdb)
    arcpy.management.CreateFileGDB(str(scratch_root), f"{run_id}.gdb")

    production_path = Path(output_workspace)
    if production_path.suffix.lower() == ".gdb":
        production_gdb = str(production_path)
        production_path.parent.mkdir(parents=True, exist_ok=True)
        if not arcpy.Exists(production_gdb):
            arcpy.management.CreateFileGDB(str(production_path.parent), production_path.name)
    else:
        production_path.mkdir(parents=True, exist_ok=True)
        production_gdb = str(production_path / settings["workspace"]["production_gdb_name"])
        if not arcpy.Exists(production_gdb):
            arcpy.management.CreateFileGDB(
                str(production_path), settings["workspace"]["production_gdb_name"]
            )

    output_dir = production_path.parent / "reports" if production_path.suffix.lower() == ".gdb" else production_path / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir = output_dir.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    spatial_evidence_dir = output_dir.parent / "spatial_evidence" if production_path.suffix.lower() == ".gdb" else production_path / "spatial_evidence"
    spatial_evidence_dir.mkdir(parents=True, exist_ok=True)
    (spatial_evidence_dir / run_id).mkdir(parents=True, exist_ok=True)

    arcpy.env.overwriteOutput = True
    arcpy.env.scratchWorkspace = scratch_gdb
    arcpy.env.workspace = scratch_gdb
    arcpy.env.outputCoordinateSystem = arcpy.SpatialReference(int(settings["client_crs"]["wkid"]))

    return RunContext(
        run_id=run_id,
        run_time_utc=run_time,
        scratch_gdb=scratch_gdb,
        production_gdb=production_gdb,
        output_dir=output_dir,
        log_dir=log_dir,
        spatial_evidence_dir=spatial_evidence_dir,
        scenario_name=scenario_name,
        aoi_name=aoi_name,
    )


def scratch_path(ctx: RunContext, name: str) -> str:
    return str(Path(ctx.scratch_gdb) / name)


def production_path(ctx: RunContext, name: str) -> str:
    return str(Path(ctx.production_gdb) / name)


def spatial_evidence_path(ctx: RunContext, name: str) -> str:
    return str(ctx.spatial_evidence_dir / ctx.run_id / name)
