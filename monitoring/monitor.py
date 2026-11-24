
"""
Industrial Machine Monitoring - MQTT Subscriber

Features:
- Subscribes to factory/# using configurable QoS.
- Decodes incoming JSON telemetry.
- Integrates with alert_system.py.
- Logs every normal MQTT message, including duplicates.
- Creates one CSV file per experiment.
- Stores Last Will messages separately.
- Handles graceful shutdown and CSV flushing.
"""

# Standard library imports
import argparse
import csv
import json
import os
import sys
import threading

from datetime import datetime, timezone
from typing import Any

# Third-party imports
import paho.mqtt.client as mqtt

# Local imports
from alert_system import evaluate_alert, handle_last_will


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

BROKER_HOST = "10.219.34.191"
BROKER_PORT = 1883

USERNAME = "factoryuser"
PASSWORD = "password123"

TOPIC = "factory/#"

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

CSV_HEADERS = [
    "recv_time",
    "topic",
    "machine_id",
    "sequence_number",
    "timestamp",
    "qos",
    "dup_flag",
    "is_alert",
    "payload_bytes",
]

# Shared experiment configuration
CONFIG = None

# CSV resources
csv_file = None
csv_writer = None
csv_lock = threading.Lock()


# ---------------------------------------------------------
# COMMAND-LINE ARGUMENTS
# ---------------------------------------------------------

def parse_arguments():

    parser = argparse.ArgumentParser(
        description="Industrial Machine MQTT Monitoring"
    )

    parser.add_argument(
        "--qos",
        type=int,
        choices=[0, 1, 2],
        required=True
    )

    parser.add_argument(
        "--loss",
        type=int,
        choices=[0, 5, 10, 20],
        required=True
    )

    parser.add_argument(
        "--delay",
        type=int,
        choices=[0, 100, 300],
        required=True
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing experiment CSV"
    )

    return parser.parse_args()


# ---------------------------------------------------------
# CSV INITIALIZATION
# ---------------------------------------------------------

def initialize_csv():

    global csv_file, csv_writer

    os.makedirs(LOG_DIR, exist_ok=True)

    filename = (
        f"qos{CONFIG.qos}_"
        f"loss{CONFIG.loss}_"
        f"delay{CONFIG.delay}.csv"
    )

    filepath = os.path.join(LOG_DIR, filename)

    # Prevent accidental loss of previous experiment data
    if os.path.exists(filepath) and not CONFIG.overwrite:
        raise FileExistsError(
            f"\nExperiment file already exists: {filepath}\n"
            "Use --overwrite only if you intentionally want to replace it."
        )

    mode = "w" if CONFIG.overwrite else "x"

    csv_file = open(
        filepath,
        mode,
        newline="",
        encoding="utf-8"
    )

    csv_writer = csv.writer(csv_file)

    # Write exact CSV headers
    csv_writer.writerow(CSV_HEADERS)

    csv_file.flush()

    print(f"\n📁 CSV logging enabled: {filepath}")

    return filepath


# ---------------------------------------------------------
# CSV MESSAGE LOGGING
# ---------------------------------------------------------

def log_message(row):

    with csv_lock:

        csv_writer.writerow(row)

        # Flush each row to reduce the chance of losing data
        csv_file.flush()


# ---------------------------------------------------------
# LAST WILL LOGGING
# ---------------------------------------------------------

def log_last_will(data, topic):

    os.makedirs(LOG_DIR, exist_ok=True)

    last_will_path = os.path.join(
        LOG_DIR,
        "last_will.log"
    )

    record = {
        "recv_time": datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z"),
        "topic": topic,
        "payload": data
    }

    with open(
        last_will_path,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(json.dumps(record) + "\n")

        f.flush()

    try:
        handle_last_will(data)
    except Exception as e:
        print(f"❗ Last Will handler error: {e}")


# ---------------------------------------------------------
# MQTT CALLBACKS
# ---------------------------------------------------------

def on_connect(client, userdata, flags, rc):

    if rc == 0:

        print(
            f"\n✅ Connected to MQTT broker "
            f"at {BROKER_HOST}:{BROKER_PORT}"
        )

        # Subscribe using experiment QoS
        client.subscribe(TOPIC, qos=CONFIG.qos)

        print(
            f"🛰️ Subscribed to {TOPIC} "
            f"with QoS {CONFIG.qos}"
        )

    else:

        print(f"❌ MQTT connection failed. Code: {rc}")


def on_message(client, userdata, msg):

    # Record arrival time immediately
    recv_time = datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    # Extract MQTT-level information
    topic = msg.topic
    qos = msg.qos
    dup_flag = int(bool(msg.dup))
    payload_bytes = len(msg.payload)

    # Decode payload
    try:

        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str)

        if not isinstance(data, dict):
            raise ValueError("JSON payload must be an object")

    except Exception as e:

        print(f"⚠️ Invalid JSON on {topic}: {e}")

        # Still log the received message
        row = [
            recv_time,
            topic,
            "",
            "",
            "",
            qos,
            dup_flag,
            0,
            payload_bytes
        ]

        log_message(row)

        return

    # Extract payload fields without changing timestamp
    machine_id = data.get("machine_id", "")
    sequence_number = data.get("sequence_number", "")

    # Preserve the publisher timestamp exactly as received
    timestamp = data.get("timestamp", "")

    # Handle Last Will separately
    if (
        isinstance(data.get("status"), str)
        and data["status"].upper() == "OFFLINE"
    ):

        print(
            f"🔌 Last Will received for machine {machine_id}"
        )

        log_last_will(data, topic)

        return

    # Alert detection
    is_alert = 0

    try:

        level = evaluate_alert(
            machine_id if machine_id else "unknown",
            data.get("temperature"),
            data.get("vibration")
        )

        is_alert = int(
            level not in ("NORMAL", "WAITING FOR DATA")
        )

    except Exception as e:

        print(f"❗ Alert evaluation error: {e}")
        level = "ALERT CHECK ERROR"

    # Create CSV row
    row = [
        recv_time,
        topic,
        machine_id,
        sequence_number,
        timestamp,
        qos,
        dup_flag,
        is_alert,
        payload_bytes
    ]

    # Log every normal telemetry message, including duplicates
    try:

        log_message(row)

        print(
            f"[📊] Machine: {machine_id} | "
            f"Sequence: {sequence_number} | "
            f"Temp: {data.get('temperature')}°C | "
            f"Vibration: {data.get('vibration')}g | "
            f"QoS: {qos} | "
            f"DUP: {dup_flag} | "
            f"Alert: {level}"
        )

    except Exception as e:

        print(f"❗ CSV logging error: {e}")


def on_disconnect(client, userdata, rc):

    if rc != 0:

        print(
            "🔌 Unexpected MQTT disconnection. "
            "Paho will attempt reconnection."
        )

    else:

        print("👋 Graceful MQTT disconnection.")


# ---------------------------------------------------------
# MAIN FUNCTION
# ---------------------------------------------------------

def main():

    global CONFIG

    CONFIG = parse_arguments()

    try:

        initialize_csv()

    except (FileExistsError, OSError) as e:

        print(f"❌ CSV initialization failed: {e}")
        sys.exit(1)

    client = mqtt.Client()

    client.username_pw_set(
        USERNAME,
        PASSWORD
    )

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    client.reconnect_delay_set(
        min_delay=1,
        max_delay=120
    )

    try:

        print("\n🚀 Starting Industrial Machine Monitor")

        print(
            f"Experiment: QoS={CONFIG.qos}, "
            f"Loss={CONFIG.loss}%, "
            f"Delay={CONFIG.delay}ms"
        )

        client.connect(
            BROKER_HOST,
            BROKER_PORT,
            keepalive=60
        )

        print("\nMonitoring started. Press Ctrl+C to stop.")

        client.loop_forever()

    except KeyboardInterrupt:

        print("\n🛑 Stopping monitoring...")

    except Exception as e:

        print(f"\n❌ MQTT error: {e}")

    finally:

        try:
            client.disconnect()
        except Exception:
            pass

        # Ensure all pending CSV data is flushed and closed
        if csv_file is not None:

            with csv_lock:

                csv_file.flush()
                csv_file.close()

            print("💾 CSV file flushed and closed.")

        print("Monitoring stopped.")


# ---------------------------------------------------------
# PROGRAM ENTRY POINT
# ---------------------------------------------------------

if __name__ == "__main__":
    main()
