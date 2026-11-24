"""
analysis.py
-----------
Reads MQTT monitor and publisher log CSVs from --input-dir, computes per-run
metrics, writes results.csv to --output-dir, and prints a console summary.

Supported filename styles (QoS / loss / delay parsed via regex):
  qos{Q}_loss{L}_delay{D}_monitor.csv   – monitor log
  qos{Q}_loss{L}_delay{D}_publisher.csv – publisher log (optional)
  qos{Q}_loss{L}_delay{D}.csv           – treated as monitor log (no publisher)

Usage:
    python analysis/analysis.py
    python analysis/analysis.py --input-dir analysis/sample_data --output-dir analysis
"""

import argparse
import os
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# CONFIG – ALL column names and alert definitions live here; change nowhere else
# ---------------------------------------------------------------------------
CONFIG = {
    # ---- Monitor log column names ----------------------------------------
    "MON_RECV_TIME":       "recv_time",
    "MON_TOPIC":           "topic",
    "MON_MACHINE_ID":      "machine_id",
    "MON_SEQ_NUM":         "sequence_number",
    "MON_TIMESTAMP":       "timestamp",
    "MON_QOS":             "qos",
    "MON_DUP_FLAG":        "dup_flag",
    "MON_IS_ALERT":        "is_alert",
    "MON_PAYLOAD_BYTES":   "payload_bytes",

    # ---- Publisher log column names --------------------------------------
    "PUB_MACHINE_ID":      "machine_id",
    "PUB_SEQ_NUM":         "sequence_number",
    "PUB_TIMESTAMP":       "timestamp",
    "PUB_QOS":             "qos",
    "PUB_LOSS_PCT":        "loss_percent",
    "PUB_DELAY_MS":        "delay_ms",
    "PUB_STATUS":          "status",   # optional; used for alert detection

    # ---- Results CSV output column names ---------------------------------
    "RES_QOS":               "qos",
    "RES_LOSS_PCT":          "loss_percent",
    "RES_DELAY_MS":          "delay_ms",
    "RES_SENT":              "sent",
    "RES_RECEIVED_UNIQUE":   "received_unique",
    "RES_LOST":              "lost",
    "RES_DELIVERY_RATIO":    "delivery_ratio",
    "RES_DUPLICATES":        "duplicates",
    "RES_DUP_RATE":          "dup_rate",
    "RES_AVG_LATENCY_MS":    "avg_latency_ms",
    "RES_MEDIAN_LATENCY_MS": "median_latency_ms",
    "RES_P95_LATENCY_MS":    "p95_latency_ms",
    "RES_MAX_LATENCY_MS":    "max_latency_ms",
    "RES_THROUGHPUT_MSG_S":  "throughput_msg_s",
    "RES_THROUGHPUT_BYTES_S": "throughput_bytes_s",
    "RES_ALERTS_SENT":       "alerts_sent",
    "RES_ALERTS_RECEIVED":   "alerts_received",
    "RES_AVG_ALERT_DELAY_MS": "avg_alert_delay_ms",

    # ---- Alert definition -----------------------------------------------
    # Publisher log "status" values that count as an alert message.
    # Add more strings here to extend alert detection without touching code.
    "ALERT_STATUSES": {"ALERT", "CRITICAL", "FAULT"},
}

# Ordered output column list derived entirely from CONFIG
RESULTS_COLUMNS = [
    CONFIG["RES_QOS"],
    CONFIG["RES_LOSS_PCT"],
    CONFIG["RES_DELAY_MS"],
    CONFIG["RES_SENT"],
    CONFIG["RES_RECEIVED_UNIQUE"],
    CONFIG["RES_LOST"],
    CONFIG["RES_DELIVERY_RATIO"],
    CONFIG["RES_DUPLICATES"],
    CONFIG["RES_DUP_RATE"],
    CONFIG["RES_AVG_LATENCY_MS"],
    CONFIG["RES_MEDIAN_LATENCY_MS"],
    CONFIG["RES_P95_LATENCY_MS"],
    CONFIG["RES_MAX_LATENCY_MS"],
    CONFIG["RES_THROUGHPUT_MSG_S"],
    CONFIG["RES_THROUGHPUT_BYTES_S"],
    CONFIG["RES_ALERTS_SENT"],
    CONFIG["RES_ALERTS_RECEIVED"],
    CONFIG["RES_AVG_ALERT_DELAY_MS"],
]

# Regex: extracts (qos, loss, delay) from any filename containing the pattern
FILENAME_RE = re.compile(r"qos(\d+)_loss(\d+)_delay(\d+)", re.IGNORECASE)

# Minimum columns required for each log type
_MONITOR_REQUIRED = {
    CONFIG["MON_RECV_TIME"],
    CONFIG["MON_MACHINE_ID"],
    CONFIG["MON_SEQ_NUM"],
    CONFIG["MON_TIMESTAMP"],
}
_PUBLISHER_REQUIRED = {
    CONFIG["PUB_MACHINE_ID"],
    CONFIG["PUB_SEQ_NUM"],
}


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def discover_runs(input_dir: str) -> list:
    """
    Scan *input_dir* for monitor/publisher CSV pairs.

    Naming rules
    ------------
    *_monitor.csv   → monitor log for that (qos, loss, delay) key
    *_publisher.csv → publisher log for that key
    *.csv (plain)   → monitor log if no *_monitor.csv exists for that key

    Returns a sorted list of dicts:
        {qos, loss_percent, delay_ms, monitor_path, publisher_path}
    publisher_path may be None when no matching publisher log is found.
    """
    runs: dict = {}

    try:
        entries = os.listdir(input_dir)
    except FileNotFoundError:
        print(f"[ERROR] Input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    for fname in entries:
        if not fname.lower().endswith(".csv"):
            continue
        m = FILENAME_RE.search(fname)
        if not m:
            continue

        key = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        fpath = os.path.join(input_dir, fname)

        if key not in runs:
            runs[key] = {
                "qos": key[0],
                "loss_percent": key[1],
                "delay_ms": key[2],
                "monitor_path": None,
                "publisher_path": None,
            }

        lower = fname.lower()
        if lower.endswith("_monitor.csv"):
            runs[key]["monitor_path"] = fpath
        elif lower.endswith("_publisher.csv"):
            runs[key]["publisher_path"] = fpath
        else:
            # Plain qos{Q}_loss{L}_delay{D}.csv → monitor fallback
            if runs[key]["monitor_path"] is None:
                runs[key]["monitor_path"] = fpath

    # Keep only runs that have at least a monitor log
    valid = [r for r in runs.values() if r["monitor_path"] is not None]
    valid.sort(key=lambda r: (r["qos"], r["loss_percent"], r["delay_ms"]))

    if not valid:
        print(
            f"[WARNING] No parseable CSV files found in '{input_dir}'.",
            file=sys.stderr,
        )
    return valid


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_csv(path: str, label: str) -> pd.DataFrame | None:
    """
    Load a CSV safely.  Returns None (with a warning) for empty or corrupt
    files; never raises.
    """
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as exc:
        warnings.warn(f"[{label}] Could not read '{path}': {exc}")
        return None

    if df.empty:
        warnings.warn(f"[{label}] File is empty: '{path}'")
        return None

    return df


def _parse_datetime_col(series: pd.Series, col_name: str) -> pd.Series:
    """
    Parse a datetime column.  Tries ISO 8601 first; falls back to interpreting
    values as Unix epoch floats (seconds).  Returns a UTC-aware Series.
    """
    try:
        return pd.to_datetime(series, utc=True, format="ISO8601")
    except (ValueError, TypeError):
        pass

    # Fallback: epoch float
    try:
        numeric = pd.to_numeric(series, errors="coerce")
        result = pd.to_datetime(numeric, unit="s", utc=True)
        warnings.warn(
            f"Column '{col_name}': ISO8601 parse failed; "
            "treating values as Unix epoch floats."
        )
        return result
    except Exception as exc:
        warnings.warn(
            f"Column '{col_name}': could not parse as datetime ({exc}). "
            "Returning NaT."
        )
        return pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")


def _warn_zero_fractions(dt_series: pd.Series, col_name: str, stem: str) -> None:
    """Warn when every timestamp has zero sub-second component (latency unreliable)."""
    valid = dt_series.dropna()
    if valid.empty:
        return
    if (valid.dt.microsecond == 0).all():
        warnings.warn(
            f"[{stem}] Column '{col_name}': all timestamps have zero fractional "
            "seconds – latency values may be unreliable (1-second resolution)."
        )


# ---------------------------------------------------------------------------
# Core metric computation
# ---------------------------------------------------------------------------

def compute_metrics(run: dict) -> dict | None:
    """
    Compute all metrics for a single run.

    Parameters
    ----------
    run : dict with keys qos, loss_percent, delay_ms,
          monitor_path, publisher_path (may be None)

    Returns
    -------
    dict of metric values, or None if the monitor log cannot be used.
    """
    qos = run["qos"]
    loss = run["loss_percent"]
    delay = run["delay_ms"]
    stem = f"qos{qos}_loss{loss}_delay{delay}"

    # ------------------------------------------------------------------ #
    # 1. Load monitor log                                                  #
    # ------------------------------------------------------------------ #
    mon = _load_csv(run["monitor_path"], stem)
    if mon is None:
        return None

    # Check required monitor columns
    missing_mon = _MONITOR_REQUIRED - set(mon.columns)
    if missing_mon:
        warnings.warn(
            f"[{stem}] Monitor log missing required columns: {missing_mon}. "
            "Skipping run."
        )
        return None

    # Parse timestamps
    c = CONFIG  # shorthand alias
    mon[c["MON_RECV_TIME"]] = _parse_datetime_col(
        mon[c["MON_RECV_TIME"]], c["MON_RECV_TIME"]
    )
    mon[c["MON_TIMESTAMP"]] = _parse_datetime_col(
        mon[c["MON_TIMESTAMP"]], c["MON_TIMESTAMP"]
    )

    # Warn about zero-fraction timestamps
    _warn_zero_fractions(mon[c["MON_RECV_TIME"]], c["MON_RECV_TIME"], stem)
    _warn_zero_fractions(mon[c["MON_TIMESTAMP"]], c["MON_TIMESTAMP"], stem)

    # ------------------------------------------------------------------ #
    # 2. Load publisher log (optional)                                     #
    # ------------------------------------------------------------------ #
    pub = None
    if run["publisher_path"]:
        pub = _load_csv(run["publisher_path"], stem + "_pub")
        if pub is not None:
            missing_pub = _PUBLISHER_REQUIRED - set(pub.columns)
            if missing_pub:
                warnings.warn(
                    f"[{stem}] Publisher log missing required columns: "
                    f"{missing_pub}. Ignoring publisher log."
                )
                pub = None

    # ------------------------------------------------------------------ #
    # 3. Compute "sent" count                                              #
    # ------------------------------------------------------------------ #
    if pub is not None:
        sent = len(pub)
    else:
        # Estimate: max(sequence_number) + 1 per machine, then sum
        seq_col = c["MON_SEQ_NUM"]
        mid_col = c["MON_MACHINE_ID"]
        if seq_col in mon.columns and mid_col in mon.columns:
            sent = int(
                mon.groupby(mid_col)[seq_col]
                .apply(lambda s: pd.to_numeric(s, errors="coerce").max() + 1)
                .fillna(0)
                .sum()
            )
            warnings.warn(
                f"[{stem}] No publisher log found. "
                f"Estimated sent={sent} from max(sequence_number)+1 per machine."
            )
        else:
            sent = len(mon)
            warnings.warn(
                f"[{stem}] No publisher log and no sequence_number column. "
                f"Estimated sent={sent} from monitor row count."
            )

    # ------------------------------------------------------------------ #
    # 4. Unique received messages                                          #
    # ------------------------------------------------------------------ #
    id_cols = [c["MON_MACHINE_ID"], c["MON_SEQ_NUM"]]
    mon_valid_ids = mon.dropna(subset=id_cols)

    # First occurrence per identity = the "true" delivery
    mon_unique = mon_valid_ids.drop_duplicates(subset=id_cols, keep="first")
    received_unique = len(mon_unique)

    # ------------------------------------------------------------------ #
    # 5. Loss and delivery ratio                                           #
    # ------------------------------------------------------------------ #
    lost = max(0, sent - received_unique)
    delivery_ratio = received_unique / sent if sent > 0 else float("nan")

    # ------------------------------------------------------------------ #
    # 6. Duplicates                                                        #
    # ------------------------------------------------------------------ #
    # Method A: explicit dup_flag column
    dup_flag_col = c["MON_DUP_FLAG"]
    if dup_flag_col in mon.columns:
        dup_by_flag = int(
            pd.to_numeric(mon[dup_flag_col], errors="coerce").fillna(0).eq(1).sum()
        )
    else:
        dup_by_flag = 0

    # Method B: identities seen more than once (extra deliveries)
    total_rows = len(mon_valid_ids)
    dup_by_identity = max(0, total_rows - received_unique)

    duplicates = max(dup_by_flag, dup_by_identity)
    total_received_rows = len(mon)
    dup_rate = (
        duplicates / total_received_rows if total_received_rows > 0 else float("nan")
    )

    # ------------------------------------------------------------------ #
    # 7. Latency (ms) = recv_time - sent timestamp                        #
    # ------------------------------------------------------------------ #
    # Use only the first occurrence of each identity for clean latency
    lat_ms = (
        (mon_unique[c["MON_RECV_TIME"]] - mon_unique[c["MON_TIMESTAMP"]])
        .dt.total_seconds()
        .mul(1000)
    )

    # Warn about / remove negative latency (clock skew)
    neg_mask = lat_ms < 0
    if neg_mask.any():
        warnings.warn(
            f"[{stem}] {neg_mask.sum()} negative latency values detected "
            "(possible clock skew). Excluded from latency statistics."
        )
        lat_ms = lat_ms[~neg_mask]

    # Remove NaN latency
    lat_ms = lat_ms.dropna()

    if lat_ms.empty:
        avg_lat = median_lat = p95_lat = max_lat = float("nan")
    else:
        avg_lat = float(lat_ms.mean())
        median_lat = float(lat_ms.median())
        p95_lat = float(np.percentile(lat_ms, 95))
        max_lat = float(lat_ms.max())

    # ------------------------------------------------------------------ #
    # 8. Throughput                                                        #
    # ------------------------------------------------------------------ #
    recv_times = mon_unique[c["MON_RECV_TIME"]].dropna()
    if len(recv_times) >= 2:
        duration_s = (recv_times.max() - recv_times.min()).total_seconds()
        duration_s = max(duration_s, 1e-6)   # guard against zero division
    else:
        duration_s = 1.0  # single message → assume 1 s window

    throughput_msg_s = received_unique / duration_s

    if c["MON_PAYLOAD_BYTES"] in mon_unique.columns:
        total_bytes = pd.to_numeric(
            mon_unique[c["MON_PAYLOAD_BYTES"]], errors="coerce"
        ).fillna(0).sum()
    else:
        total_bytes = 0.0

    throughput_bytes_s = float(total_bytes) / duration_s

    # ------------------------------------------------------------------ #
    # 9. Alert metrics                                                     #
    # ------------------------------------------------------------------ #
    is_alert_col = c["MON_IS_ALERT"]

    # Alerts received = unique alert identities in monitor log
    if is_alert_col in mon_unique.columns:
        alert_mask_mon = (
            pd.to_numeric(mon_unique[is_alert_col], errors="coerce").fillna(0).eq(1)
        )
        mon_alerts = mon_unique[alert_mask_mon]
    else:
        mon_alerts = pd.DataFrame()

    alerts_received = len(mon_alerts)

    # Alerts sent
    pub_status_col = c["PUB_STATUS"]
    alert_statuses = c["ALERT_STATUSES"]

    if pub is not None and pub_status_col in pub.columns:
        # Count publisher rows whose status is in ALERT_STATUSES
        alerts_sent = int(
            pub[pub_status_col].str.strip().str.upper().isin(
                {s.upper() for s in alert_statuses}
            ).sum()
        )
    else:
        # Fallback: use unique alert identities visible in monitor log
        alerts_sent = alerts_received
        warnings.warn(
            f"[{stem}] Publisher log has no '{pub_status_col}' column. "
            "alerts_sent set to alerts_received; alerts_lost is a lower bound."
        )

    alerts_lost = max(0, alerts_sent - alerts_received)

    # Average alert latency (first delivery of each alert identity)
    if not mon_alerts.empty:
        alert_lat = (
            (mon_alerts[c["MON_RECV_TIME"]] - mon_alerts[c["MON_TIMESTAMP"]])
            .dt.total_seconds()
            .mul(1000)
        )
        alert_lat = alert_lat[alert_lat >= 0].dropna()
        avg_alert_delay = float(alert_lat.mean()) if not alert_lat.empty else float("nan")
    else:
        avg_alert_delay = float("nan")

    # ------------------------------------------------------------------ #
    # 10. Assemble result row                                              #
    # ------------------------------------------------------------------ #
    return {
        c["RES_QOS"]:               qos,
        c["RES_LOSS_PCT"]:          loss,
        c["RES_DELAY_MS"]:          delay,
        c["RES_SENT"]:              sent,
        c["RES_RECEIVED_UNIQUE"]:   received_unique,
        c["RES_LOST"]:              lost,
        c["RES_DELIVERY_RATIO"]:    round(delivery_ratio, 4),
        c["RES_DUPLICATES"]:        duplicates,
        c["RES_DUP_RATE"]:          round(dup_rate, 4),
        c["RES_AVG_LATENCY_MS"]:    round(avg_lat, 2),
        c["RES_MEDIAN_LATENCY_MS"]: round(median_lat, 2),
        c["RES_P95_LATENCY_MS"]:    round(p95_lat, 2),
        c["RES_MAX_LATENCY_MS"]:    round(max_lat, 2),
        c["RES_THROUGHPUT_MSG_S"]:  round(throughput_msg_s, 4),
        c["RES_THROUGHPUT_BYTES_S"]: round(throughput_bytes_s, 2),
        c["RES_ALERTS_SENT"]:       alerts_sent,
        c["RES_ALERTS_RECEIVED"]:   alerts_received,
        c["RES_AVG_ALERT_DELAY_MS"]: round(avg_alert_delay, 2),
    }


# ---------------------------------------------------------------------------
# Console summary table
# ---------------------------------------------------------------------------

def print_summary_table(df: pd.DataFrame) -> None:
    """Print a formatted console summary of key metrics from results DataFrame."""
    c = CONFIG
    sep = "-" * 100

    header = (
        f"{'QoS':>4} {'Loss%':>6} {'Delay':>6} {'Sent':>6} "
        f"{'RecvUniq':>9} {'Lost':>6} {'DelRatio':>9} "
        f"{'Dups':>6} {'AvgLat':>8} {'P95Lat':>8} "
        f"{'Thru(m/s)':>10} {'AlrtSnt':>8} {'AlrtRcv':>8}"
    )
    print("\n" + sep)
    print("  MQTT QoS ANALYSIS RESULTS SUMMARY")
    print(sep)
    print(header)
    print(sep)

    for _, row in df.iterrows():
        print(
            f"{int(row[c['RES_QOS']]):>4} "
            f"{int(row[c['RES_LOSS_PCT']]):>6} "
            f"{int(row[c['RES_DELAY_MS']]):>6} "
            f"{int(row[c['RES_SENT']]):>6} "
            f"{int(row[c['RES_RECEIVED_UNIQUE']]):>9} "
            f"{int(row[c['RES_LOST']]):>6} "
            f"{row[c['RES_DELIVERY_RATIO']]:>9.4f} "
            f"{int(row[c['RES_DUPLICATES']]):>6} "
            f"{row[c['RES_AVG_LATENCY_MS']]:>8.1f} "
            f"{row[c['RES_P95_LATENCY_MS']]:>8.1f} "
            f"{row[c['RES_THROUGHPUT_MSG_S']]:>10.3f} "
            f"{int(row[c['RES_ALERTS_SENT']]):>8} "
            f"{int(row[c['RES_ALERTS_RECEIVED']]):>8}"
        )

    print(sep)
    print(f"  Total runs: {len(df)}")
    print(sep + "\n")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    # Resolve paths relative to this script's location for convenient defaults
    script_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description=(
            "Analyse MQTT monitor/publisher logs and produce results.csv "
            "with per-run QoS metrics."
        )
    )
    parser.add_argument(
        "--input-dir",
        default=str(script_dir / "sample_data"),
        help="Directory containing monitor/publisher CSV log files "
             "(default: analysis/sample_data/)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(script_dir),
        help="Directory to write results.csv (default: analysis/)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Discover runs, compute metrics for each, write results.csv."""
    args = parse_args()
    input_dir = args.input_dir
    output_dir = args.output_dir

    print(f"\nInput  directory : {input_dir}")
    print(f"Output directory : {output_dir}\n")

    # Discover run files
    runs = discover_runs(input_dir)
    if not runs:
        print("No runs found. Exiting.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(runs)} run(s) to analyse.\n")

    # Compute metrics for every run
    results = []
    skipped = 0
    for run in runs:
        stem = (
            f"qos{run['qos']}_loss{run['loss_percent']}"
            f"_delay{run['delay_ms']}"
        )
        metrics = compute_metrics(run)
        if metrics is None:
            print(f"  [SKIP] {stem}")
            skipped += 1
        else:
            results.append(metrics)
            print(f"  [OK]   {stem}")

    if not results:
        print("\n[ERROR] All runs were skipped. No results to write.", file=sys.stderr)
        sys.exit(1)

    # Build results DataFrame with consistent column order
    df = pd.DataFrame(results, columns=RESULTS_COLUMNS)

    # Write results.csv
    os.makedirs(output_dir, exist_ok=True)
    results_path = os.path.join(output_dir, "results.csv")
    df.to_csv(results_path, index=False)
    print(f"\nResults written to: {results_path}")
    print(f"Runs analysed: {len(results)}  |  Skipped: {skipped}\n")

    # Print console summary table
    print_summary_table(df)


if __name__ == "__main__":
    main()
