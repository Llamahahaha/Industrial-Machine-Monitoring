"""
analysis.py
-----------
Reads MQTT monitor and publisher log CSVs from --input-dir, computes per-run
metrics, writes results.csv to --output-dir, prints a console summary, and
generates 9 PNG graphs into --output-dir/graphs/.

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

import matplotlib
matplotlib.use("Agg")          # non-interactive backend; must precede pyplot
import matplotlib.pyplot as plt
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
    # Publisher log "status" values counted as alert messages.
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

# Regex: extracts (qos, loss, delay) from any filename with the pattern
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
# Graph constants  (one colour per QoS, consistent across all plots)
# ---------------------------------------------------------------------------
QOS_COLORS = {0: "#2196F3", 1: "#FF9800", 2: "#4CAF50"}
QOS_LABELS = {
    0: "QoS 0 (at-most-once)",
    1: "QoS 1 (at-least-once)",
    2: "QoS 2 (exactly-once)",
}
GRAPH_DPI = 200
GRAPH_FIGSIZE = (10, 6)
_DELAY_SUBTITLE = "Averaged across delay values (0 / 100 / 300 ms)"
_LOSS_SUBTITLE = "Averaged across loss values (0 / 5 / 10 / 20 %)"


# ===========================================================================
# File discovery
# ===========================================================================

def discover_runs(input_dir: str) -> list:
    """
    Scan *input_dir* for monitor/publisher CSV pairs.

    Naming rules
    ------------
    *_monitor.csv   → monitor log for that (qos, loss, delay) key
    *_publisher.csv → publisher log for that key
    *.csv (plain)   → monitor log if no *_monitor.csv exists for that key

    Returns a sorted list of dicts with keys:
        qos, loss_percent, delay_ms, monitor_path, publisher_path
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
            # Plain qos{Q}_loss{L}_delay{D}.csv → monitor fallback only
            if runs[key]["monitor_path"] is None:
                runs[key]["monitor_path"] = fpath

    # Keep only runs that have at least a monitor log; sort by (qos, loss, delay)
    valid = [r for r in runs.values() if r["monitor_path"] is not None]
    valid.sort(key=lambda r: (r["qos"], r["loss_percent"], r["delay_ms"]))

    if not valid:
        print(
            f"[WARNING] No parseable CSV files found in '{input_dir}'.",
            file=sys.stderr,
        )
    return valid


# ===========================================================================
# I/O helpers
# ===========================================================================

def _load_csv(path: str, label: str) -> "pd.DataFrame | None":
    """Load a CSV safely. Returns None (with a warning) for empty/corrupt files."""
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
    Parse a datetime column.
    Tries ISO 8601 first; falls back to interpreting values as Unix epoch
    floats (seconds since 1970-01-01).  Returns a UTC-aware Series.
    """
    try:
        return pd.to_datetime(series, utc=True, format="ISO8601")
    except (ValueError, TypeError):
        pass

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
    """Warn when every timestamp has zero sub-second component (1-s resolution)."""
    valid = dt_series.dropna()
    if valid.empty:
        return
    if (valid.dt.microsecond == 0).all():
        warnings.warn(
            f"[{stem}] Column '{col_name}': all timestamps have zero fractional "
            "seconds – latency values may be unreliable (1-second resolution)."
        )


# ===========================================================================
# Core metric computation
# ===========================================================================

def compute_metrics(run: dict) -> "dict | None":
    """
    Compute all metrics for a single run.

    Parameters
    ----------
    run : dict with keys qos, loss_percent, delay_ms,
          monitor_path, publisher_path (may be None)

    Returns
    -------
    dict of metric values keyed by RESULTS_COLUMNS names, or None on failure.
    """
    qos = run["qos"]
    loss = run["loss_percent"]
    delay = run["delay_ms"]
    stem = f"qos{qos}_loss{loss}_delay{delay}"
    c = CONFIG   # local alias keeps lines short

    # ------------------------------------------------------------------ #
    # 1. Load monitor log                                                  #
    # ------------------------------------------------------------------ #
    mon = _load_csv(run["monitor_path"], stem)
    if mon is None:
        return None

    missing_mon = _MONITOR_REQUIRED - set(mon.columns)
    if missing_mon:
        warnings.warn(
            f"[{stem}] Monitor log missing required columns: {missing_mon}. "
            "Skipping run."
        )
        return None

    mon[c["MON_RECV_TIME"]] = _parse_datetime_col(
        mon[c["MON_RECV_TIME"]], c["MON_RECV_TIME"]
    )
    mon[c["MON_TIMESTAMP"]] = _parse_datetime_col(
        mon[c["MON_TIMESTAMP"]], c["MON_TIMESTAMP"]
    )
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

    # First occurrence per identity = the canonical delivery row
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
            pd.to_numeric(mon[dup_flag_col], errors="coerce")
            .fillna(0)
            .eq(1)
            .sum()
        )
    else:
        dup_by_flag = 0

    # Method B: extra deliveries of repeated identities
    total_rows = len(mon_valid_ids)
    dup_by_identity = max(0, total_rows - received_unique)

    duplicates = max(dup_by_flag, dup_by_identity)
    total_received_rows = len(mon)
    dup_rate = (
        duplicates / total_received_rows
        if total_received_rows > 0
        else float("nan")
    )

    # ------------------------------------------------------------------ #
    # 7. Latency (ms)  =  recv_time − sent timestamp                      #
    # ------------------------------------------------------------------ #
    lat_ms = (
        (mon_unique[c["MON_RECV_TIME"]] - mon_unique[c["MON_TIMESTAMP"]])
        .dt.total_seconds()
        .mul(1000)
    )

    neg_mask = lat_ms < 0
    if neg_mask.any():
        warnings.warn(
            f"[{stem}] {neg_mask.sum()} negative latency values detected "
            "(possible clock skew). Excluded from latency statistics."
        )
        lat_ms = lat_ms[~neg_mask]

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
        duration_s = max(duration_s, 1e-6)
    else:
        duration_s = 1.0

    throughput_msg_s = received_unique / duration_s

    if c["MON_PAYLOAD_BYTES"] in mon_unique.columns:
        total_bytes = (
            pd.to_numeric(mon_unique[c["MON_PAYLOAD_BYTES"]], errors="coerce")
            .fillna(0)
            .sum()
        )
    else:
        total_bytes = 0.0

    throughput_bytes_s = float(total_bytes) / duration_s

    # ------------------------------------------------------------------ #
    # 9. Alert metrics                                                     #
    # ------------------------------------------------------------------ #
    is_alert_col = c["MON_IS_ALERT"]

    # Alerts received = unique alert identities seen in monitor log
    if is_alert_col in mon_unique.columns:
        alert_mask_mon = (
            pd.to_numeric(mon_unique[is_alert_col], errors="coerce")
            .fillna(0)
            .eq(1)
        )
        mon_alerts = mon_unique[alert_mask_mon]
    else:
        mon_alerts = pd.DataFrame()

    alerts_received = len(mon_alerts)

    # Alerts sent
    pub_status_col = c["PUB_STATUS"]
    alert_statuses_upper = {s.upper() for s in c["ALERT_STATUSES"]}

    if pub is not None and pub_status_col in pub.columns:
        # Count publisher rows whose status is in ALERT_STATUSES.
        # This correctly counts dropped alert messages (QoS 0 + loss > 0)
        # that never appear in the monitor log.
        alerts_sent = int(
            pub[pub_status_col]
            .astype(str)
            .str.strip()
            .str.upper()
            .isin(alert_statuses_upper)
            .sum()
        )
    else:
        # Fallback: best-effort estimate from monitor log only
        alerts_sent = alerts_received
        warnings.warn(
            f"[{stem}] Publisher log has no '{pub_status_col}' column. "
            "alerts_sent set to alerts_received; alerts_lost is a lower bound."
        )

    # Average alert delivery latency (first delivery of each alert identity)
    if not mon_alerts.empty:
        alert_lat = (
            (mon_alerts[c["MON_RECV_TIME"]] - mon_alerts[c["MON_TIMESTAMP"]])
            .dt.total_seconds()
            .mul(1000)
        )
        alert_lat = alert_lat[alert_lat >= 0].dropna()
        avg_alert_delay = (
            float(alert_lat.mean()) if not alert_lat.empty else float("nan")
        )
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


# ===========================================================================
# Console summary table
# ===========================================================================

def print_summary_table(df: pd.DataFrame) -> None:
    """Print a formatted console summary of key metrics."""
    c = CONFIG
    sep = "-" * 104

    header = (
        f"{'QoS':>4} {'Loss%':>6} {'Delay':>6} {'Sent':>6} "
        f"{'RecvUniq':>9} {'Lost':>6} {'DelRatio':>9} "
        f"{'Dups':>6} {'AvgLat':>8} {'P95Lat':>8} "
        f"{'Thru(m/s)':>10} {'AlrtSnt':>8} {'AlrtRcv':>8}"
    )
    print(f"\n{sep}")
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
    print(f"{sep}\n")


# ===========================================================================
# Graph helpers
# ===========================================================================

def _save_fig(fig: plt.Figure, path: str) -> None:
    """Save *fig* to *path* at GRAPH_DPI and close it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, dpi=GRAPH_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path}")


def _agg_vs_loss(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Return mean of *metric* grouped by (qos, loss_percent), averaged over delays."""
    c = CONFIG
    return (
        df.groupby([c["RES_QOS"], c["RES_LOSS_PCT"]])[metric]
        .mean()
        .reset_index()
    )


def _agg_vs_delay(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Return mean of *metric* grouped by (qos, delay_ms), averaged over loss values."""
    c = CONFIG
    return (
        df.groupby([c["RES_QOS"], c["RES_DELAY_MS"]])[metric]
        .mean()
        .reset_index()
    )


def _collect_latencies_by_qos(input_dir: str) -> dict:
    """
    Load per-message latencies from all monitor logs, grouped by QoS level.
    Returns {qos_int: [latency_ms, ...]} for use in the boxplot.
    """
    latencies: dict = {}
    c = CONFIG
    needed = {
        c["MON_RECV_TIME"], c["MON_TIMESTAMP"],
        c["MON_MACHINE_ID"], c["MON_SEQ_NUM"],
    }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # already warned during metric pass
        for fname in sorted(os.listdir(input_dir)):
            if not fname.lower().endswith("_monitor.csv"):
                continue
            m = FILENAME_RE.search(fname)
            if not m:
                continue
            qos = int(m.group(1))
            df = _load_csv(os.path.join(input_dir, fname), fname)
            if df is None or not needed.issubset(df.columns):
                continue

            df[c["MON_RECV_TIME"]] = _parse_datetime_col(
                df[c["MON_RECV_TIME"]], c["MON_RECV_TIME"]
            )
            df[c["MON_TIMESTAMP"]] = _parse_datetime_col(
                df[c["MON_TIMESTAMP"]], c["MON_TIMESTAMP"]
            )

            id_cols = [c["MON_MACHINE_ID"], c["MON_SEQ_NUM"]]
            df_uniq = (
                df.dropna(subset=id_cols)
                  .drop_duplicates(subset=id_cols, keep="first")
            )

            lat = (
                (df_uniq[c["MON_RECV_TIME"]] - df_uniq[c["MON_TIMESTAMP"]])
                .dt.total_seconds()
                .mul(1000)
            )
            lat = lat[lat >= 0].dropna().tolist()
            latencies.setdefault(qos, []).extend(lat)

    return latencies


# ===========================================================================
# Individual graph functions
# ===========================================================================

def plot_latency_vs_loss(df: pd.DataFrame, graphs_dir: str) -> None:
    """Average delivery latency (ms) vs packet-loss %, one line per QoS."""
    c = CONFIG
    metric = c["RES_AVG_LATENCY_MS"]
    agg = _agg_vs_loss(df, metric)

    fig, ax = plt.subplots(figsize=GRAPH_FIGSIZE)
    for qos in sorted(df[c["RES_QOS"]].unique()):
        sub = agg[agg[c["RES_QOS"]] == qos]
        ax.plot(
            sub[c["RES_LOSS_PCT"]], sub[metric],
            marker="o", linewidth=2,
            color=QOS_COLORS.get(qos, "gray"),
            label=QOS_LABELS.get(qos, f"QoS {qos}"),
        )

    ax.set_xlabel("Packet Loss (%)")
    ax.set_ylabel("Average Delivery Latency (ms)")
    ax.set_title(
        "Average Latency vs Packet Loss by QoS\n"
        f"({_DELAY_SUBTITLE})"
    )
    ax.legend()
    ax.grid(True, alpha=0.3)
    _save_fig(fig, os.path.join(graphs_dir, "latency_vs_loss.png"))


def plot_delivery_ratio_vs_loss(df: pd.DataFrame, graphs_dir: str) -> None:
    """Delivery ratio (0–1) vs packet-loss %, one line per QoS."""
    c = CONFIG
    metric = c["RES_DELIVERY_RATIO"]
    agg = _agg_vs_loss(df, metric)

    fig, ax = plt.subplots(figsize=GRAPH_FIGSIZE)
    for qos in sorted(df[c["RES_QOS"]].unique()):
        sub = agg[agg[c["RES_QOS"]] == qos]
        ax.plot(
            sub[c["RES_LOSS_PCT"]], sub[metric],
            marker="o", linewidth=2,
            color=QOS_COLORS.get(qos, "gray"),
            label=QOS_LABELS.get(qos, f"QoS {qos}"),
        )

    ax.set_xlabel("Packet Loss (%)")
    ax.set_ylabel("Delivery Ratio")
    ax.set_ylim(0, 1.05)
    ax.set_title(
        "Message Delivery Ratio vs Packet Loss by QoS\n"
        f"({_DELAY_SUBTITLE})"
    )
    ax.legend()
    ax.grid(True, alpha=0.3)
    _save_fig(fig, os.path.join(graphs_dir, "delivery_ratio_vs_loss.png"))


def plot_duplicates_vs_loss(df: pd.DataFrame, graphs_dir: str) -> None:
    """Duplicate message count vs packet-loss %, one line per QoS."""
    c = CONFIG
    metric = c["RES_DUPLICATES"]
    agg = _agg_vs_loss(df, metric)

    fig, ax = plt.subplots(figsize=GRAPH_FIGSIZE)
    for qos in sorted(df[c["RES_QOS"]].unique()):
        sub = agg[agg[c["RES_QOS"]] == qos]
        ax.plot(
            sub[c["RES_LOSS_PCT"]], sub[metric],
            marker="o", linewidth=2,
            color=QOS_COLORS.get(qos, "gray"),
            label=QOS_LABELS.get(qos, f"QoS {qos}"),
        )

    ax.set_xlabel("Packet Loss (%)")
    ax.set_ylabel("Duplicate Message Count (per 300 sent)")
    ax.set_title(
        "Duplicate Messages vs Packet Loss by QoS\n"
        f"({_DELAY_SUBTITLE})"
    )
    ax.legend()
    ax.grid(True, alpha=0.3)
    _save_fig(fig, os.path.join(graphs_dir, "duplicates_vs_loss.png"))


def plot_throughput_vs_loss(df: pd.DataFrame, graphs_dir: str) -> None:
    """Message throughput (msg/s) vs packet-loss %, one line per QoS."""
    c = CONFIG
    metric = c["RES_THROUGHPUT_MSG_S"]
    agg = _agg_vs_loss(df, metric)

    fig, ax = plt.subplots(figsize=GRAPH_FIGSIZE)
    for qos in sorted(df[c["RES_QOS"]].unique()):
        sub = agg[agg[c["RES_QOS"]] == qos]
        ax.plot(
            sub[c["RES_LOSS_PCT"]], sub[metric],
            marker="o", linewidth=2,
            color=QOS_COLORS.get(qos, "gray"),
            label=QOS_LABELS.get(qos, f"QoS {qos}"),
        )

    ax.set_xlabel("Packet Loss (%)")
    ax.set_ylabel("Throughput (messages / second)")
    ax.set_title(
        "Message Throughput vs Packet Loss by QoS\n"
        f"({_DELAY_SUBTITLE})"
    )
    ax.legend()
    ax.grid(True, alpha=0.3)
    _save_fig(fig, os.path.join(graphs_dir, "throughput_vs_loss.png"))


def plot_alert_delay_vs_loss(df: pd.DataFrame, graphs_dir: str) -> None:
    """Average alert message latency (ms) vs packet-loss %, one line per QoS."""
    c = CONFIG
    metric = c["RES_AVG_ALERT_DELAY_MS"]
    agg = _agg_vs_loss(df, metric)

    fig, ax = plt.subplots(figsize=GRAPH_FIGSIZE)
    for qos in sorted(df[c["RES_QOS"]].unique()):
        sub = agg[agg[c["RES_QOS"]] == qos].dropna(subset=[metric])
        ax.plot(
            sub[c["RES_LOSS_PCT"]], sub[metric],
            marker="o", linewidth=2,
            color=QOS_COLORS.get(qos, "gray"),
            label=QOS_LABELS.get(qos, f"QoS {qos}"),
        )

    ax.set_xlabel("Packet Loss (%)")
    ax.set_ylabel("Average Alert Delivery Latency (ms)")
    ax.set_title(
        "Alert Message Latency vs Packet Loss by QoS\n"
        f"({_DELAY_SUBTITLE})"
    )
    ax.legend()
    ax.grid(True, alpha=0.3)
    _save_fig(fig, os.path.join(graphs_dir, "alert_delay_vs_loss.png"))


def plot_alerts_lost_vs_loss(df: pd.DataFrame, graphs_dir: str) -> None:
    """
    Number of alert messages lost vs packet-loss %, one line per QoS.
    alerts_lost = alerts_sent − alerts_received (clamped ≥ 0).
    Expected: QoS 0 rises with loss; QoS 1/2 stay at 0.
    """
    c = CONFIG
    df = df.copy()
    df["alerts_lost"] = (
        df[c["RES_ALERTS_SENT"]] - df[c["RES_ALERTS_RECEIVED"]]
    ).clip(lower=0)

    agg = _agg_vs_loss(df, "alerts_lost")

    fig, ax = plt.subplots(figsize=GRAPH_FIGSIZE)
    for qos in sorted(df[c["RES_QOS"]].unique()):
        sub = agg[agg[c["RES_QOS"]] == qos]
        ax.plot(
            sub[c["RES_LOSS_PCT"]], sub["alerts_lost"],
            marker="o", linewidth=2,
            color=QOS_COLORS.get(qos, "gray"),
            label=QOS_LABELS.get(qos, f"QoS {qos}"),
        )

    ax.set_xlabel("Packet Loss (%)")
    ax.set_ylabel("Alert Messages Lost (count)")
    ax.set_title(
        "Alert Messages Lost vs Packet Loss by QoS\n"
        f"({_DELAY_SUBTITLE})"
    )
    ax.legend()
    ax.grid(True, alpha=0.3)
    _save_fig(fig, os.path.join(graphs_dir, "alerts_lost_vs_loss.png"))


def plot_latency_vs_delay(df: pd.DataFrame, graphs_dir: str) -> None:
    """Average delivery latency (ms) vs one-way delay (ms), one line per QoS."""
    c = CONFIG
    metric = c["RES_AVG_LATENCY_MS"]
    agg = _agg_vs_delay(df, metric)

    fig, ax = plt.subplots(figsize=GRAPH_FIGSIZE)
    for qos in sorted(df[c["RES_QOS"]].unique()):
        sub = agg[agg[c["RES_QOS"]] == qos]
        ax.plot(
            sub[c["RES_DELAY_MS"]], sub[metric],
            marker="o", linewidth=2,
            color=QOS_COLORS.get(qos, "gray"),
            label=QOS_LABELS.get(qos, f"QoS {qos}"),
        )

    ax.set_xlabel("One-Way Network Delay (ms)")
    ax.set_ylabel("Average Delivery Latency (ms)")
    ax.set_title(
        "Average Latency vs Network Delay by QoS\n"
        f"({_LOSS_SUBTITLE})"
    )
    ax.legend()
    ax.grid(True, alpha=0.3)
    _save_fig(fig, os.path.join(graphs_dir, "latency_vs_delay.png"))


def plot_latency_boxplot_by_qos(input_dir: str, graphs_dir: str) -> None:
    """
    Box-and-whisker plot of per-message delivery latency grouped by QoS.
    Raw monitor logs are loaded to get per-message latency values across
    all runs (all network conditions combined).
    """
    latencies = _collect_latencies_by_qos(input_dir)
    if not latencies:
        warnings.warn("No latency data collected for boxplot.")
        return

    qos_levels = sorted(latencies.keys())
    data = [latencies[q] for q in qos_levels]
    tick_labels = [QOS_LABELS.get(q, f"QoS {q}") for q in qos_levels]
    colors = [QOS_COLORS.get(q, "gray") for q in qos_levels]

    fig, ax = plt.subplots(figsize=GRAPH_FIGSIZE)
    bp = ax.boxplot(
        data,
        patch_artist=True,
        notch=False,
        medianprops=dict(color="black", linewidth=2),
        flierprops=dict(marker=".", markersize=2, alpha=0.3),
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_xticks(range(1, len(qos_levels) + 1))
    ax.set_xticklabels(tick_labels, fontsize=9)
    ax.set_xlabel("QoS Level")
    ax.set_ylabel("Delivery Latency (ms)")
    ax.set_title(
        "Message Delivery Latency Distribution by QoS\n"
        "(all runs and network conditions combined)"
    )
    ax.grid(True, axis="y", alpha=0.3)
    _save_fig(fig, os.path.join(graphs_dir, "latency_boxplot_by_qos.png"))


def plot_summary_dashboard(df: pd.DataFrame, graphs_dir: str) -> None:
    """
    2 × 3 dashboard of key metrics (all vs packet-loss %, averaged over delays).
    Panels: Latency | Delivery Ratio | Duplicates
            Throughput | Alert Delay | Alerts Lost
    """
    c = CONFIG
    df = df.copy()
    df["alerts_lost"] = (
        df[c["RES_ALERTS_SENT"]] - df[c["RES_ALERTS_RECEIVED"]]
    ).clip(lower=0)

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(
        "MQTT QoS Performance — Summary Dashboard",
        fontsize=14,
        fontweight="bold",
    )

    # (axis, metric_key, y-label, panel title)
    panels = [
        (axes[0, 0], c["RES_AVG_LATENCY_MS"],    "Avg Latency (ms)",      "Latency vs Loss"),
        (axes[0, 1], c["RES_DELIVERY_RATIO"],     "Delivery Ratio",        "Delivery Ratio vs Loss"),
        (axes[0, 2], c["RES_DUPLICATES"],         "Duplicate Count",       "Duplicates vs Loss"),
        (axes[1, 0], c["RES_THROUGHPUT_MSG_S"],   "Throughput (msg/s)",    "Throughput vs Loss"),
        (axes[1, 1], c["RES_AVG_ALERT_DELAY_MS"], "Alert Latency (ms)",    "Alert Delay vs Loss"),
        (axes[1, 2], "alerts_lost",               "Alerts Lost",           "Alerts Lost vs Loss"),
    ]

    for ax, metric, ylabel, title in panels:
        agg = _agg_vs_loss(df, metric)
        for qos in sorted(df[c["RES_QOS"]].unique()):
            sub = agg[agg[c["RES_QOS"]] == qos].dropna(subset=[metric])
            ax.plot(
                sub[c["RES_LOSS_PCT"]], sub[metric],
                marker="o", linewidth=2,
                color=QOS_COLORS.get(qos, "gray"),
                label=QOS_LABELS.get(qos, f"QoS {qos}"),
            )
        ax.set_xlabel("Packet Loss (%)", fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(title, fontsize=10)
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    fig.text(
        0.5, 0.01,
        _DELAY_SUBTITLE,
        ha="center",
        fontsize=9,
        style="italic",
        color="dimgray",
    )
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    _save_fig(fig, os.path.join(graphs_dir, "summary_dashboard.png"))


# ===========================================================================
# Graph orchestrator
# ===========================================================================

def generate_graphs(
    df: pd.DataFrame, input_dir: str, graphs_dir: str
) -> None:
    """Generate all 9 PNG graphs into *graphs_dir*."""
    os.makedirs(graphs_dir, exist_ok=True)
    print(f"\nGenerating graphs → {graphs_dir}\n")

    plot_latency_vs_loss(df, graphs_dir)
    plot_delivery_ratio_vs_loss(df, graphs_dir)
    plot_duplicates_vs_loss(df, graphs_dir)
    plot_throughput_vs_loss(df, graphs_dir)
    plot_alert_delay_vs_loss(df, graphs_dir)
    plot_alerts_lost_vs_loss(df, graphs_dir)
    plot_latency_vs_delay(df, graphs_dir)
    plot_latency_boxplot_by_qos(input_dir, graphs_dir)
    plot_summary_dashboard(df, graphs_dir)

    print("\nAll graphs saved.\n")


# ===========================================================================
# Argument parsing
# ===========================================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    script_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description=(
            "Analyse MQTT monitor/publisher logs and produce results.csv "
            "with per-run QoS metrics, plus 9 PNG graphs."
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
        help="Directory to write results.csv and graphs/ (default: analysis/)",
    )
    return parser.parse_args()


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    """Discover runs, compute metrics, write results.csv, generate graphs."""
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
        print(
            "\n[ERROR] All runs were skipped. No results to write.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Build DataFrame with consistent column order
    df = pd.DataFrame(results, columns=RESULTS_COLUMNS)

    # Write results.csv
    os.makedirs(output_dir, exist_ok=True)
    results_path = os.path.join(output_dir, "results.csv")
    df.to_csv(results_path, index=False)
    print(f"\nResults written to: {results_path}")
    print(f"Runs analysed: {len(results)}  |  Skipped: {skipped}\n")

    # Print console summary table
    print_summary_table(df)

    # Generate all graphs
    graphs_dir = os.path.join(output_dir, "graphs")
    generate_graphs(df, input_dir, graphs_dir)


if __name__ == "__main__":
    main()
