'''monitor.py

Simple MQTT subscriber for an Industrial Machine Monitoring System.

Features:
- Connects to a Mosquitto broker (configurable IP and port).
- Subscribes to the topic ``factory/#`` to receive data from any machine.
- Decodes JSON payloads and prints ``machine_id``, ``temperature``, ``vibration`` and ``status``.
- Handles connection loss and attempts to reconnect.
- Runs continuously until the program is stopped (Ctrl+C).

This script is aimed at beginners – each function is documented with clear comments.
'''

import json
import sys
import time
from typing import Any


import paho.mqtt.client as mqtt
from alert_system import process_telemetry, handle_last_will


# ---------------------------------------------------------------------------
# Configuration – edit these values to match your MQTT broker.
# ---------------------------------------------------------------------------
BROKER_HOST = "10.219.34.191"   # Broker IP address (e.g., "192.168.1.100")
BROKER_PORT = 1883  

USERNAME = "factoryuser"
PASSWORD = "password123"        # Broker port (default for Mosquitto is 1883)
TOPIC = "factory/#"         # Subscribe to all sub‑topics under "factory/"

# ---------------------------------------------------------------------------
# Callback functions – MQTT invokes these when certain events happen.
# ---------------------------------------------------------------------------

def on_connect(client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
    """Called when the client connects to the broker.

    * ``rc`` is the connection result – 0 means success.
    * If the connection is successful we subscribe to the topic.
    """
    if rc == 0:
        print(f"✅ Connected to MQTT broker at {BROKER_HOST}:{BROKER_PORT}")
        # Subscribe to the topic; qos=1 ensures at‑least‑once delivery.
        client.subscribe(TOPIC, qos=1)
        print(f"🛰️  Subscribed to topic '{TOPIC}'")
    else:
        print(f"❌ Connection failed with code {rc}. See https://mqtt.org/documentation for codes.")


def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    """Called for each incoming message on a subscribed topic.

    The payload should be a JSON dict. If it contains a normal telemetry
    payload we forward it to ``process_telemetry`` which prints a concise
    status line (NORMAL / WARNING / CRITICAL). If the payload is a Last
    Will indicating the machine went OFFLINE we forward it to
    ``handle_last_will``.
    """
    try:
        payload_str = msg.payload.decode('utf-8')
        data = json.loads(payload_str)
    except json.JSONDecodeError:
        print(f"⚠️  Received non‑JSON payload on topic {msg.topic}: {msg.payload}")
        return
    except Exception as e:
        print(f"❗ Unexpected error decoding message: {e}")
        return

    # Detect a Last Will (offline) message – convention: status field == "OFFLINE"
    if isinstance(data.get('status'), str) and data['status'].upper() == 'OFFLINE':
        try:
            handle_last_will(data)
        except Exception as e:
            print(f"❗ Error handling Last Will: {e}")
        return

    # Normal telemetry – let the alert system decide the level and print it
    try:
        process_telemetry(data)
    except Exception as e:
        print(f"❗ Error processing telemetry: {e}")


def on_disconnect(client: mqtt.Client, userdata: Any, rc: int) -> None:
    """Called when the client disconnects from the broker.

    ``rc`` == 0 means a graceful disconnect (e.g., we called ``client.disconnect()``).
    Any other value indicates an unexpected loss of connection – we try to reconnect.
    """
    if rc != 0:
        print("🔌 Disconnected unexpectedly. Trying to reconnect…")
        # The client will automatically attempt to reconnect if ``loop_forever``
        # is used, but we can also explicitly call ``reconnect``.
        try:
            client.reconnect()
        except Exception as e:
            print(f"❌ Reconnection failed: {e}. Will keep trying…")
    else:
        print("👋 Graceful disconnect.")

# ---------------------------------------------------------------------------
# Main entry point – set up the client and start the network loop.
# ---------------------------------------------------------------------------

def main() -> None:
    # Create an MQTT client instance. ``client_id`` is optional – Mosquitto will assign one.
    client = mqtt.Client()
    # Set username and password for broker authentication
    client.username_pw_set(USERNAME, PASSWORD)
    # Register callbacks
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # Optional: enable automatic reconnect with exponential back‑off (default behaviour).
    client.reconnect_delay_set(min_delay=1, max_delay=120)

    # Connect to the broker inside a try/except to catch connection errors early.
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    except Exception as e:
        print(f"❌ Could not connect to broker at {BROKER_HOST}:{BROKER_PORT}: {e}")
        sys.exit(1)

    # ``loop_forever`` blocks the thread and handles network traffic, reconnections,
    # and dispatches callbacks. It will run until the user interrupts (Ctrl+C).
    try:
        print("🚀 Starting MQTT loop – press Ctrl+C to stop.")
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user. Shutting down…")
    finally:
        client.disconnect()
        # Give a moment for the disconnect callback to fire.
        time.sleep(1)

if __name__ == "__main__":
    main()
