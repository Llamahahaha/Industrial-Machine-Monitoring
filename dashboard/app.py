#!/usr/bin/env python3
"""Streamlit Dashboard for Industrial Machine Monitoring Network

This dashboard aggregates live MQTT telemetry, status alerts, and historic experiment
results (CSV) into an interactive web UI. It is deliberately lightweight and does
not modify any of C's or S's modules – it merely consumes their output.
"""

import os
import json
import threading
import time
from datetime import datetime, timezone
from collections import defaultdict

import pandas as pd
import streamlit as st
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load configuration from .env (broker address, credentials)
# ---------------------------------------------------------------------------
load_dotenv()
MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

# ---------------------------------------------------------------------------
# Shared state (thread‑safe because only the MQTT thread writes)
# ---------------------------------------------------------------------------
telemetry_store = {}
status_store = {}
alert_store = []  # list of dicts with alert details

store_lock = threading.Lock()

# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        st.sidebar.success("✅ Connected to MQTT broker")
        # Subscribe to telemetry and status for all machines
        client.subscribe("factory/+/telemetry", qos=1)
        client.subscribe("factory/+/status", qos=1)
    else:
        st.sidebar.error(f"❌ MQTT connection failed (rc={rc})")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        # ignore malformed payloads
        return

    topic_parts = msg.topic.split('/')
    if len(topic_parts) != 3:
        return
    _, machine_id, msg_type = topic_parts

    with store_lock:
        if msg_type == "telemetry":
            telemetry_store[machine_id] = payload
        elif msg_type == "status":
            status_store[machine_id] = payload
            # Simple alert logic – high temperature / vibration etc.
            if payload.get("status") == "WARNING":
                alert_store.append({
                    "machine_id": machine_id,
                    "type": "WARNING",
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "detail": "Abnormal sensor reading"
                })
            elif payload.get("status") == "OFFLINE":
                alert_store.append({
                    "machine_id": machine_id,
                    "type": "OFFLINE",
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "detail": "Machine disconnected"
                })

# ---------------------------------------------------------------------------
# MQTT background thread
# ---------------------------------------------------------------------------

def mqtt_thread():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dashboard_client", protocol=mqtt.MQTTv311)
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

threading.Thread(target=mqtt_thread, daemon=True).start()

# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Industrial Machine Monitoring Dashboard", layout="wide")
st.title("Industrial Machine Monitoring Network Dashboard")

# Tabs for the different sections described in the spec
live_tab, alerts_tab, perf_tab, net_tab, compare_tab, experiment_tab = st.tabs([
    "Live Monitoring",
    "Alerts",
    "MQTT Performance",
    "Network Conditions",
    "QoS Comparison",
    "Experiment Explorer"
])

# ---------------------------------------------------------------------------
# Live Monitoring tab
# ---------------------------------------------------------------------------
with live_tab:
    st.header("Live Machine Overview")
    # Create a table from the latest telemetry + status
    data_rows = []
    with store_lock:
        for mid in sorted(telemetry_store.keys()):
            tel = telemetry_store.get(mid, {})
            stat = status_store.get(mid, {})
            data_rows.append({
                "Machine ID": mid,
                "Status": stat.get("status", "UNKNOWN"),
                "Temperature": tel.get("temperature"),
                "Vibration": tel.get("vibration"),
                "Seq": tel.get("sequence_number"),
                "Last TS": tel.get("timestamp"),
            })
    if data_rows:
        df_live = pd.DataFrame(data_rows)
        st.dataframe(df_live, hide_index=True)
    else:
        st.info("Waiting for telemetry…")

# ---------------------------------------------------------------------------
# Alerts tab
# ---------------------------------------------------------------------------
with alerts_tab:
    st.header("Recent Alerts")
    with store_lock:
        recent = sorted(alert_store, key=lambda x: x["timestamp"], reverse=True)[:20]
    if recent:
        df_alerts = pd.DataFrame(recent)
        st.table(df_alerts)
    else:
        st.info("No alerts recorded yet.")

# ---------------------------------------------------------------------------
# MQTT Performance tab (very lightweight – derived from live data)
# ---------------------------------------------------------------------------
with perf_tab:
    st.header("MQTT Performance Metrics (Live Approximation)")
    # Simple counters
    with store_lock:
        total_msgs = len(telemetry_store)
    st.metric(label="Messages received (since page load)", value=total_msgs)
    st.caption("For detailed delivery‑ratio, loss, latency, and duplicate counts, refer to the experiment CSVs in the Experiment tab.")

# ---------------------------------------------------------------------------
# Network Conditions tab – shows current tc netem settings if available
# ---------------------------------------------------------------------------
with net_tab:
    st.header("Current Network Impairment Settings")
    # Run a quick `tc qdisc show` on the detected interface (requires sudo).
    # We do not automatically invoke privileged commands – instead we display a hint.
    st.info(
        "To view the active netem configuration, run the following command on the host:"
        "\n\n```bash\nsudo tc qdisc show dev <interface>\n```"
    )

# ---------------------------------------------------------------------------
# QoS Comparison tab – loads historic CSV if present
# ---------------------------------------------------------------------------
with compare_tab:
    st.header("QoS Experiment Comparison")
    csv_path = os.path.abspath("analysis/graphs/results.csv")
    if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
        df = pd.read_csv(csv_path)
        st.subheader("Raw Results")
        st.dataframe(df)
        # Example visual: loss percent vs qos
        st.subheader("Loss % by QoS")
        chart = df.groupby("qos")["loss_percent"].mean().reset_index()
        st.bar_chart(chart.set_index("qos"))
    else:
        st.info("No experimental CSV data available yet. Run experiments and ensure results are saved to `analysis/graphs/results.csv`.")

# ---------------------------------------------------------------------------
# Experiment Explorer tab – filter and view trials
# ---------------------------------------------------------------------------
with experiment_tab:
    st.header("Experiment Explorer")
    csv_path = os.path.abspath("analysis/graphs/results.csv")
    if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
        df = pd.read_csv(csv_path)
        # Sidebar filters
        qos_options = st.multiselect("QoS level", options=sorted(df["qos"].unique()), default=sorted(df["qos"].unique()))
        trial_ids = st.multiselect("Trial ID", options=sorted(df["trial_id"].unique()), default=sorted(df["trial_id"].unique()))
        machine_ids = st.multiselect("Machine ID", options=sorted(df["machine_id"].unique()), default=sorted(df["machine_id"].unique()))
        filtered = df[(df["qos"].isin(qos_options)) & (df["trial_id"].isin(trial_ids)) & (df["machine_id"].isin(machine_ids))]
        st.dataframe(filtered)
    else:
        st.info("Experiment results CSV not found.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.caption("Dashboard built with Streamlit – live telemetry is updated in near‑real time. "
             "All credentials are loaded from the project's .env and never logged.")
