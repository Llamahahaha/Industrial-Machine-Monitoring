"""Service layer that wraps the existing analysis.py module for API use."""

import os
import re
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Add project root to path so we can import analysis module
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))

from analysis import discover_runs, compute_metrics, _load_csv, _parse_datetime_col, CONFIG, FILENAME_RE

# Directories
LOGS_DIR = str(PROJECT_ROOT / "monitoring" / "logs")
SAMPLE_DIR = str(PROJECT_ROOT / "analysis" / "sample_data")

CSV_HEADERS = [
    "recv_time", "topic", "machine_id", "sequence_number",
    "timestamp", "qos", "dup_flag", "is_alert", "payload_bytes",
]


def _safe_filename(filename: str) -> bool:
    """Validate filename to prevent path traversal."""
    return (
        filename.endswith(".csv")
        and "/" not in filename
        and "\\" not in filename
        and ".." not in filename
    )


def list_experiments(input_dir: str = None) -> list:
    """List all experiment CSV files with metadata."""
    d = input_dir or LOGS_DIR
    if not os.path.isdir(d):
        return []

    experiments = []
    for fname in sorted(os.listdir(d)):
        if not fname.lower().endswith(".csv"):
            continue
        fpath = os.path.join(d, fname)
        m = FILENAME_RE.search(fname)
        stat = os.stat(fpath)
        exp = {
            "filename": fname,
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
            "qos": int(m.group(1)) if m else None,
            "loss_percent": int(m.group(2)) if m else None,
            "delay_ms": int(m.group(3)) if m else None,
        }
        experiments.append(exp)
    return experiments


def get_latest_experiment(input_dir: str = None) -> Optional[dict]:
    """Return the most recently modified experiment file info."""
    exps = list_experiments(input_dir)
    if not exps:
        return None
    return max(exps, key=lambda e: e["modified"])


def load_experiment_csv(filename: str, input_dir: str = None) -> Optional[pd.DataFrame]:
    """Load a specific experiment CSV safely."""
    if not _safe_filename(filename):
        return None
    d = input_dir or LOGS_DIR
    fpath = os.path.join(d, filename)
    if not os.path.isfile(fpath):
        return None
    try:
        df = pd.read_csv(fpath, low_memory=False)
        return df
    except Exception:
        return None


def compute_experiment_metrics(filename: str, input_dir: str = None) -> Optional[dict]:
    """Compute metrics for a single experiment file using the analysis module."""
    if not _safe_filename(filename):
        return None
    d = input_dir or LOGS_DIR
    fpath = os.path.join(d, filename)
    if not os.path.isfile(fpath):
        return None

    m = FILENAME_RE.search(filename)
    if not m:
        return None

    run = {
        "qos": int(m.group(1)),
        "loss_percent": int(m.group(2)),
        "delay_ms": int(m.group(3)),
        "monitor_path": fpath,
        "publisher_path": None,
    }

    # Check for publisher file
    base = f"qos{run['qos']}_loss{run['loss_percent']}_delay{run['delay_ms']}"
    pub_path = os.path.join(d, f"{base}_publisher.csv")
    if os.path.isfile(pub_path):
        run["publisher_path"] = pub_path

    return compute_metrics(run)


def get_experiment_data(filename: str, input_dir: str = None) -> Optional[dict]:
    """Get full experiment data for the Last Simulation / Analysis tabs."""
    if not _safe_filename(filename):
        return None
    d = input_dir or LOGS_DIR
    df = load_experiment_csv(filename, d)
    if df is None:
        return None

    m = FILENAME_RE.search(filename)
    stat = os.stat(os.path.join(d, filename))

    # Parse timestamps for latency calculation
    records = df.to_dict(orient="records")

    # Calculate per-message latency if both timestamps exist
    has_timestamps = "recv_time" in df.columns and "timestamp" in df.columns
    
    # Compute sequence gaps per machine
    missing_sequences = {}
    duplicate_sequences = {}
    if "machine_id" in df.columns and "sequence_number" in df.columns:
        for mid, group in df.groupby("machine_id"):
            seqs = pd.to_numeric(group["sequence_number"], errors="coerce").dropna().astype(int)
            if len(seqs) > 0:
                expected = set(range(int(seqs.min()), int(seqs.max()) + 1))
                actual = set(seqs.tolist())
                missing_sequences[str(mid)] = sorted(expected - actual)
                # Count duplicates by sequence
                dup_count = len(seqs) - len(actual)
                duplicate_sequences[str(mid)] = max(0, dup_count)

    # Time series data for charts (sample to avoid huge payloads)
    max_points = 500
    step = max(1, len(records) // max_points)
    sampled = records[::step]

    # Calculate latencies
    latencies = []
    if has_timestamps:
        try:
            rt = _parse_datetime_col(df["recv_time"], "recv_time")
            ts = _parse_datetime_col(df["timestamp"], "timestamp")
            lat = ((rt - ts).dt.total_seconds() * 1000).dropna()
            lat = lat[lat >= 0]
            latencies = lat.tolist()
        except Exception:
            pass

    # Alert distribution
    alert_count = 0
    normal_count = 0
    if "is_alert" in df.columns:
        alert_series = pd.to_numeric(df["is_alert"], errors="coerce").fillna(0)
        alert_count = int(alert_series.eq(1).sum())
        normal_count = int(alert_series.eq(0).sum())

    # Duplicate count
    dup_count = 0
    if "dup_flag" in df.columns:
        dup_count = int(pd.to_numeric(df["dup_flag"], errors="coerce").fillna(0).eq(1).sum())

    # Throughput over time (messages per second bins)
    throughput_series = []
    if "recv_time" in df.columns:
        try:
            rt = _parse_datetime_col(df["recv_time"], "recv_time")
            valid = rt.dropna()
            if len(valid) > 1:
                bins = pd.cut(valid, bins=min(50, len(valid)//2 or 1))
                counts = bins.value_counts().sort_index()
                for interval, count in counts.items():
                    mid = interval.mid
                    throughput_series.append({
                        "time": str(mid),
                        "messages": int(count),
                    })
        except Exception:
            pass

    return {
        "filename": filename,
        "modified": stat.st_mtime,
        "qos": int(m.group(1)) if m else None,
        "loss_percent": int(m.group(2)) if m else None,
        "delay_ms": int(m.group(3)) if m else None,
        "total_messages": len(df),
        "total_alerts": alert_count,
        "total_normal": normal_count,
        "total_duplicates": dup_count,
        "has_temperature": False,  # CSV schema doesn't include temp/vib columns
        "has_vibration": False,
        "messages": sampled,
        "missing_sequences": missing_sequences,
        "duplicate_sequences": duplicate_sequences,
        "latencies": latencies[:500],  # Limit for payload size
        "throughput": throughput_series,
        "columns": list(df.columns),
    }
