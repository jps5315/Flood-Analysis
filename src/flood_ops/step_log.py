"""Structured step logging for execution investigation.

Records each operation with: step name, run/step IDs, input metadata,
CRS, parameters, feature counts, elapsed time, warnings, and status.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class StepRecord:
    run_id: str
    step_id: str
    step_name: str
    start_time_utc: datetime
    end_time_utc: datetime | None = None
    elapsed_seconds: float | None = None
    crs_wkid: int = 3083
    input_metadata: dict[str, Any] | None = None
    feature_counts: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    warnings: list[str] | None = None
    status: str = "IN_PROGRESS"
    error_message: str | None = None


class StepLogger:
    """Manages structured step logging for a run."""

    def __init__(self, run_id: str, log_dir: Path, crs_wkid: int = 3083):
        self.run_id = run_id
        self.log_dir = log_dir
        self.crs_wkid = crs_wkid
        self.steps: list[StepRecord] = []
        self.log_file = log_dir / f"step_log_{run_id}.json"

    def start_step(
        self,
        step_name: str,
        input_metadata: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Start a new step and return its step ID."""
        step_id = f"STP_{uuid.uuid4().hex[:8]}"
        step = StepRecord(
            run_id=self.run_id,
            step_id=step_id,
            step_name=step_name,
            start_time_utc=datetime.now(timezone.utc),
            crs_wkid=self.crs_wkid,
            input_metadata=input_metadata,
            parameters=parameters,
            warnings=[],
            status="IN_PROGRESS",
        )
        self.steps.append(step)
        return step_id

    def complete_step(
        self,
        step_id: str,
        feature_counts: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        """Mark a step as completed with results."""
        for step in self.steps:
            if step.step_id == step_id:
                step.end_time_utc = datetime.now(timezone.utc)
                step.elapsed_seconds = (step.end_time_utc - step.start_time_utc).total_seconds()
                step.feature_counts = feature_counts
                step.warnings = warnings or []
                step.status = "SUCCESS"
                break

    def fail_step(self, step_id: str, error_message: str) -> None:
        """Mark a step as failed."""
        for step in self.steps:
            if step.step_id == step_id:
                step.end_time_utc = datetime.now(timezone.utc)
                step.elapsed_seconds = (step.end_time_utc - step.start_time_utc).total_seconds()
                step.status = "FAILED"
                step.error_message = error_message
                break

    def write_log(self) -> None:
        """Write all steps to JSON log file."""
        log_data = {
            "run_id": self.run_id,
            "total_steps": len(self.steps),
            "successful_steps": sum(1 for s in self.steps if s.status == "SUCCESS"),
            "failed_steps": sum(1 for s in self.steps if s.status == "FAILED"),
            "steps": [self._step_to_dict(s) for s in self.steps],
        }
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, default=str)

    def _step_to_dict(self, step: StepRecord) -> dict[str, Any]:
        """Convert StepRecord to dict for JSON serialization."""
        d = asdict(step)
        d["start_time_utc"] = d["start_time_utc"].isoformat()
        if d["end_time_utc"]:
            d["end_time_utc"] = d["end_time_utc"].isoformat()
        return d
