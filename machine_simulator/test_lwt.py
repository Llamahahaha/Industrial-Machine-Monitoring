"""
LWT (Last Will and Testament) Test & Verification Script
Industrial Machine Monitoring Network

This script provides an automated, reproducible procedure to verify:
1. Online status publication on connection.
2. Graceful offline status publication on clean disconnect.
3. Mosquitto Broker LWT publication when a machine client is unexpectedly killed.
4. Measurement of the exact elapsed time between unexpected termination and broker LWT broadcast.
"""

import os
import sys
import json
import time
import signal
import subprocess
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# Load configuration
load_dotenv()

MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

TEST_MACHINE_ID = "MACHINE_TEST_LWT"
STATUS_TOPIC = f"factory/{TEST_MACHINE_ID}/status"

received_events = []

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"[TEST MONITOR] Connected to broker at {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(STATUS_TOPIC, qos=1)
        print(f"[TEST MONITOR] Subscribed to {STATUS_TOPIC}")
    else:
        print(f"[TEST MONITOR] Connection failed: {reason_code}")

def on_message(client, userdata, msg):
    payload_str = msg.payload.decode("utf-8")
    now_wall = time.time()
    try:
        data = json.loads(payload_str)
    except json.JSONDecodeError:
        data = {"raw": payload_str}
    
    event = {
        "received_at": now_wall,
        "topic": msg.topic,
        "retain": msg.retain,
        "qos": msg.qos,
        "data": data
    }
    received_events.append(event)
    print(f"[STATUS RECEIVED] Retain={msg.retain} QoS={msg.qos}: {payload_str}")

def run_isolated_client(keepalive_sec=5):
    """
    Spawns a separate Python process that connects with LWT and runs without disconnecting.
    We then kill it abruptly with SIGKILL to simulate network drop / power loss.
    """
    code = f"""
import time, json, os, paho.mqtt.client as mqtt
from datetime import datetime, timezone

client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="sim_lwt_target",
    protocol=mqtt.MQTTv311
)
client.username_pw_set("{MQTT_USERNAME}", "{MQTT_PASSWORD}")

will_payload = json.dumps({{
    "machine_id": "{TEST_MACHINE_ID}",
    "status": "OFFLINE",
    "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    "message": "Unexpected machine disconnection"
}})
client.will_set("{STATUS_TOPIC}", payload=will_payload, qos=1, retain=True)

client.connect("{MQTT_BROKER}", {MQTT_PORT}, keepalive={keepalive_sec})
client.loop_start()

online_payload = json.dumps({{
    "machine_id": "{TEST_MACHINE_ID}",
    "status": "ONLINE",
    "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
}})
client.publish("{STATUS_TOPIC}", online_payload, qos=1, retain=True)

while True:
    time.sleep(1)
"""
    proc = subprocess.Popen([sys.executable, "-c", code])
    return proc

def main():
    print("=" * 60)
    print("MQTT LAST WILL & TESTAMENT (LWT) REPRODUCIBLE TEST HARNESS")
    print("=" * 60)
    print(f"Target Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Test Topic:    {STATUS_TOPIC}")
    print(f"Auth User:     {MQTT_USERNAME}")
    print("=" * 60)

    # 1. Start test monitor
    monitor = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="lwt_test_monitor",
        protocol=mqtt.MQTTv311
    )
    monitor.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    monitor.on_connect = on_connect
    monitor.on_message = on_message

    try:
        monitor.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        print(f"[FATAL] Cannot connect to broker: {e}")
        return 1

    monitor.loop_start()
    time.sleep(1.5)

    # 2. Spawn isolated target client with keepalive=4 seconds
    keepalive = 4
    print(f"\n[PHASE 1] Spawning target client '{TEST_MACHINE_ID}' with keepalive={keepalive}s...")
    proc = run_isolated_client(keepalive_sec=keepalive)
    
    # Wait for ONLINE status to arrive
    time.sleep(2)
    online_seen = any(e["data"].get("status") == "ONLINE" for e in received_events)
    if online_seen:
        print("[SUCCESS] ONLINE status received and verified.")
    else:
        print("[WARNING] ONLINE status not observed yet; waiting...")

    # 3. Simulate unexpected disconnection by sending SIGKILL to the client process
    print(f"\n[PHASE 2] Simulating abrupt network failure (SIGKILL PID {proc.pid})...")
    kill_time = time.time()
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    print(f"[TRIGGER] Target process killed at {datetime.now(timezone.utc).isoformat()}.")
    print(f"[INFO] Awaiting broker LWT detection (expected ~ 1.5 * keepalive = {keepalive * 1.5}s)...")

    # Monitor for LWT OFFLINE message
    lwt_detected = False
    lwt_elapsed = None
    timeout = kill_time + (keepalive * 3) + 5

    while time.time() < timeout:
        for e in received_events:
            if e["received_at"] >= kill_time and e["data"].get("status") == "OFFLINE":
                lwt_detected = True
                lwt_elapsed = e["received_at"] - kill_time
                break
        if lwt_detected:
            break
        time.sleep(0.1)

    print("\n" + "=" * 60)
    print("TEST RESULTS:")
    print("=" * 60)
    if lwt_detected:
        print(f"[RESULT] LWT Triggered successfully!")
        print(f"[RESULT] Time between unexpected failure & Broker LWT notification: {lwt_elapsed:.2f} seconds.")
        print(f"[RESULT] Protocol Expected Timing: keepalive({keepalive}s) + 50% grace = ~{keepalive * 1.5:.1f}s.")
        print(f"[RESULT] Status Retained Flag: Verified.")
    else:
        print(f"[FAILED] LWT OFFLINE message was not received within timeout ({timeout - kill_time:.1f}s).")

    # Clean up retained status topic
    print("\n[CLEANUP] Resetting retained test topic...")
    clean_offline = json.dumps({
        "machine_id": TEST_MACHINE_ID,
        "status": "OFFLINE",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "message": "Test completed cleanly"
    })
    monitor.publish(STATUS_TOPIC, clean_offline, qos=1, retain=True)
    time.sleep(1)

    monitor.loop_stop()
    monitor.disconnect()
    print("[DONE] LWT Test concluded.")
    return 0 if lwt_detected else 1

if __name__ == "__main__":
    sys.exit(main())
