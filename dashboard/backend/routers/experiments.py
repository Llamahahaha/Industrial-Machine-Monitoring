"""Experiment analysis routes."""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from analysis_service import (
    list_experiments,
    get_latest_experiment,
    compute_experiment_metrics,
    get_experiment_data,
    LOGS_DIR,
    SAMPLE_DIR,
)

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _resolve_dir(source: Optional[str]) -> str:
    """Resolve input directory from query param."""
    if source == "sample":
        return SAMPLE_DIR
    return LOGS_DIR


@router.get("")
async def get_experiments(source: Optional[str] = Query(None)):
    """List all experiment CSV files."""
    d = _resolve_dir(source)
    return {"experiments": list_experiments(d), "source_dir": d}


@router.get("/latest")
async def get_latest(source: Optional[str] = Query(None)):
    """Get the most recently modified experiment."""
    d = _resolve_dir(source)
    exp = get_latest_experiment(d)
    if not exp:
        raise HTTPException(status_code=404, detail="No experiments found")
    # Also get full data
    data = get_experiment_data(exp["filename"], d)
    metrics = compute_experiment_metrics(exp["filename"], d)
    return {"experiment": exp, "data": data, "metrics": metrics}


@router.get("/{filename}")
async def get_experiment(filename: str, source: Optional[str] = Query(None)):
    """Get full data for a specific experiment."""
    d = _resolve_dir(source)
    data = get_experiment_data(filename, d)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Experiment '{filename}' not found")
    return {"data": data}


@router.get("/{filename}/metrics")
async def get_experiment_metrics(filename: str, source: Optional[str] = Query(None)):
    """Compute metrics for a specific experiment."""
    d = _resolve_dir(source)
    metrics = compute_experiment_metrics(filename, d)
    if metrics is None:
        raise HTTPException(status_code=404, detail=f"Cannot compute metrics for '{filename}'")
    return {"metrics": metrics}
