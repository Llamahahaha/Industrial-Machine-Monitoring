"""
generate_sample_data.py
-----------------------
Generates realistic synthetic MQTT monitor and publisher log files for all
combinations of QoS {0, 1, 2} x loss_percent {0, 5, 10, 20} x delay_ms
{0, 100, 300}.

Outputs two CSV files per combination into analysis/sample_data/:
  qos{Q}_loss{L}_delay{D}_monitor.csv
  qos{Q}_loss{L}_delay{D}_publisher.csv

QoS behaviour modelled:
  QoS 0 : messages dropped with probability = loss_percent/100, no duplicates,
           lowest base latency.
  QoS 1 : no message loss, possible duplicates (dup_flag=1) from retransmits,
           moderate extra latency on retransmit.
  QoS 2 : no message loss, no duplicates, highest base latency (4-way
           handshake overhead).

Usage:
    python analysis/generate_sample_data.py
    python analysis/generate_sample_data.py --output-dir analysis/sample_data
"""

import argparse
import csv
import json
import os
import random
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MACHINES = [f"MACHINE_{i:02d}" for i in range(1, 6)]   # 5 machines
MESSAGES_PER_MACHINE = 60                                # ~1 msg/s for 60 s
ALERT_PROBABILITY = 0.05                                 # 5 % of msgs are alerts

QOS_VALUES = [0, 1, 2]
LOSS_VALUES = [0, 5, 10, 20]      # percent
DELAY_VALUES = [0, 100, 300]      # milliseconds

# Base one-way latency (ms) added on top of network delay, by QoS level
BASE_LATENCY_MS = {
    0: 5,    # fire-and-forget, minimal stack overhead
    1: 15,   # PUBACK round-trip overhead
    2: 35,   # PUBREC + PUBREL + PUBCOMP overhead
}

# Jitter range (±ms) around the base latency
LATENCY_JITTER_MS = {
    0: 3,
    1: 10,
    2: 20,
}

# Extra latency added per retransmit for QoS 1 (ms)
RETRANSMIT_EXTRA_MS = 20

MONITOR_COLUMNS = [
    "recv_time", "topic", "machine_id", "sequence_number",
    "timestamp", "qos", "dup_flag", "is_alert", "payload_bytes",
]

PUBLISHER_COLUMNS = [
    "machine_id", "sequence_number", "timestamp", "qos",
    "loss_percent", "delay_ms", "status",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with milliseconds."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _jitter(base_ms: float, jitter_ms: float) -> float:
    """Return base_ms ± uniform jitter, clamped to ≥ 0."""
    return max(0.0, base_ms + random.uniform(-jitter_ms, jitter_ms))


def _make_payload(machine_id: str, seq: int, sent_dt: datetime,
                  temperature: float, vibration: float,
                  status: str = "RUNNING") -> dict:
    """Build the JSON payload dict."""
    return {
        "machine_id": machine_id,
        "timestamp": _iso(sent_dt),
        "sequence_number": seq,
        "temperature": round(temperature, 2),
        "vibration": round(vibration, 2),
        "status": status,
    }


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

def generate_run(qos: int, loss_percent: int, delay_ms: int,
                 run_start: datetime) -> tuple:
    """
    Simulate one run and return (monitor_rows, publisher_rows).

    Parameters
    ----------
    qos          : MQTT QoS level (0, 1, or 2)
    loss_percent : simulated network packet-loss percentage
    delay_ms     : one-way network delay in milliseconds
    run_start    : UTC datetime for the start of this run

    Returns
    -------
    monitor_rows   : list of dicts matching MONITOR_COLUMNS
    publisher_rows : list of dicts matching PUBLISHER_COLUMNS
    """
    monitor_rows: list = []
    publisher_rows: list = []

    loss_prob = loss_percent / 100.0

    for machine_id in MACHINES:
        # Each machine starts sending at a random sub-second offset
        machine_offset = timedelta(milliseconds=random.uniform(0, 500))

        for seq in range(1, MESSAGES_PER_MACHINE + 1):
            # Time this message was sent (1 msg/s cadence + small jitter)
            sent_offset = timedelta(
                seconds=(seq - 1) + random.uniform(-0.05, 0.05)
            )
            sent_dt = run_start + machine_offset + sent_offset

            # Sensor values with realistic variation
            temperature = random.gauss(75.0, 5.0)
            vibration = random.gauss(4.0, 0.8)
            is_alert = int(random.random() < ALERT_PROBABILITY)
            topic = f"factory/{machine_id.lower()}/temperature"
            status = "ALERT" if is_alert else "RUNNING"

            payload = _make_payload(
                machine_id, seq, sent_dt, temperature, vibration, status
            )
            payload_bytes = len(json.dumps(payload))

            # --- Publisher log row (always recorded, including dropped msgs) ---
            # "status" matches the message's alert flag so analysis.py can
            # count alerts_sent from the publisher log even when QoS 0 drops
            # some of those alert messages before they reach the monitor.
            publisher_rows.append({
                "machine_id": machine_id,
                "sequence_number": seq,
                "timestamp": _iso(sent_dt),
                "qos": qos,
                "loss_percent": loss_percent,
                "delay_ms": delay_ms,
                "status": status,       # "ALERT" or "RUNNING"
            })

            # --- Delivery simulation per QoS ---
            if qos == 0:
                # Drop with probability = loss_prob; no retransmit, no dup
                if random.random() < loss_prob:
                    continue  # message lost, nothing logged at monitor

                latency_ms = (
                    delay_ms
                    + _jitter(BASE_LATENCY_MS[0], LATENCY_JITTER_MS[0])
                )
                recv_dt = sent_dt + timedelta(milliseconds=latency_ms)
                monitor_rows.append({
                    "recv_time": _iso(recv_dt),
                    "topic": topic,
                    "machine_id": machine_id,
                    "sequence_number": seq,
                    "timestamp": _iso(sent_dt),
                    "qos": qos,
                    "dup_flag": 0,
                    "is_alert": is_alert,
                    "payload_bytes": payload_bytes,
                })

            elif qos == 1:
                # No loss; first delivery always arrives
                latency_ms = (
                    delay_ms
                    + _jitter(BASE_LATENCY_MS[1], LATENCY_JITTER_MS[1])
                )
                recv_dt = sent_dt + timedelta(milliseconds=latency_ms)
                monitor_rows.append({
                    "recv_time": _iso(recv_dt),
                    "topic": topic,
                    "machine_id": machine_id,
                    "sequence_number": seq,
                    "timestamp": _iso(sent_dt),
                    "qos": qos,
                    "dup_flag": 0,
                    "is_alert": is_alert,
                    "payload_bytes": payload_bytes,
                })

                # Duplicate probability scales linearly with packet loss.
                # At 0 % loss every PUBACK arrives → no retransmit → 0 dups.
                # As loss rises, more PUBACKs are dropped, the publisher
                # times out and retransmits with dup_flag=1, raising the rate.
                # (Real QoS 1 can dup on timeout even without loss, but that
                # is omitted here so the 0%-loss baseline is clean for graphs.)
                dup_prob = min(0.30, loss_prob * 1.5)
                if random.random() < dup_prob:
                    extra_ms = latency_ms + RETRANSMIT_EXTRA_MS + random.uniform(0, 20)
                    recv_dup = sent_dt + timedelta(milliseconds=extra_ms)
                    monitor_rows.append({
                        "recv_time": _iso(recv_dup),
                        "topic": topic,
                        "machine_id": machine_id,
                        "sequence_number": seq,
                        "timestamp": _iso(sent_dt),
                        "qos": qos,
                        "dup_flag": 1,
                        "is_alert": is_alert,
                        "payload_bytes": payload_bytes,
                    })

            else:  # qos == 2
                # No loss, no duplicates; higher latency from 4-way handshake
                latency_ms = (
                    delay_ms
                    + _jitter(BASE_LATENCY_MS[2], LATENCY_JITTER_MS[2])
                )
                recv_dt = sent_dt + timedelta(milliseconds=latency_ms)
                monitor_rows.append({
                    "recv_time": _iso(recv_dt),
                    "topic": topic,
                    "machine_id": machine_id,
                    "sequence_number": seq,
                    "timestamp": _iso(sent_dt),
                    "qos": qos,
                    "dup_flag": 0,
                    "is_alert": is_alert,
                    "payload_bytes": payload_bytes,
                })

    # Shuffle monitor rows to simulate interleaved delivery order
    random.shuffle(monitor_rows)
    return monitor_rows, publisher_rows


def write_csv(filepath: str, rows: list, columns: list) -> None:
    """Write a list of dicts to a CSV file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Written: {filepath}  ({len(rows)} rows)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic MQTT monitor and publisher log CSVs."
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(os.path.dirname(__file__), "sample_data"),
        help="Directory to write generated CSV files (default: analysis/sample_data/)",
    )
    args = parser.parse_args()
    output_dir = args.output_dir

    # Fixed run-start anchor; each combination gets its own 60-s window
    base_start = datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc)
    combo_index = 0

    total_combos = len(QOS_VALUES) * len(LOSS_VALUES) * len(DELAY_VALUES)
    print(f"Generating {total_combos} run combinations → {output_dir}\n")

    random.seed(42)  # reproducible output

    for qos in QOS_VALUES:
        for loss in LOSS_VALUES:
            for delay in DELAY_VALUES:
                # Stagger run windows so timestamps don't overlap
                run_start = base_start + timedelta(minutes=combo_index * 2)
                combo_index += 1

                stem = f"qos{qos}_loss{loss}_delay{delay}"
                print(f"[{combo_index:02d}/{total_combos}] {stem}")

                monitor_rows, publisher_rows = generate_run(
                    qos, loss, delay, run_start
                )

                write_csv(
                    os.path.join(output_dir, f"{stem}_monitor.csv"),
                    monitor_rows,
                    MONITOR_COLUMNS,
                )
                write_csv(
                    os.path.join(output_dir, f"{stem}_publisher.csv"),
                    publisher_rows,
                    PUBLISHER_COLUMNS,
                )

    print(f"\nDone. Generated {combo_index * 2} CSV files in '{output_dir}'.")


if __name__ == "__main__":
    main()
