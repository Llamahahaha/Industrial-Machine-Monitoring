import threading
import json
import random
import signal
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from config import (
    MQTT_BROKER,
    MQTT_PORT,
    MQTT_USERNAME,
    MQTT_PASSWORD,
    MACHINE_COUNT,
    PUBLISH_INTERVAL,
    MQTT_QOS,
    TEMPERATURE_THRESHOLD,
    VIBRATION_THRESHOLD,
)


class MachineSimulator:
    def __init__(self, machine_id):
        self.machine_id = machine_id
        self.sequence_number = 0
        self.running = True

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"simulator_{machine_id}",
            protocol=mqtt.MQTTv311,
        )

        self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        # Publish OFFLINE if this machine disconnects unexpectedly.
        will_payload = json.dumps({
            "machine_id": self.machine_id,
            "status": "OFFLINE",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "message": "Unexpected machine disconnection",
        })

        self.client.will_set(
            f"factory/{self.machine_id}/status",
            payload=will_payload,
            qos=1,
            retain=True,
        )

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print(f"[CONNECTED] {self.machine_id} connected to broker")
        else:
            print(f"[ERROR] {self.machine_id}: connection failed: {reason_code}")

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        print(f"[DISCONNECTED] {self.machine_id}: {reason_code}")

    def generate_telemetry(self):
        temperature = round(random.uniform(55.0, 95.0), 2)
        vibration = round(random.uniform(1.0, 10.0), 2)

        if temperature >= TEMPERATURE_THRESHOLD or vibration >= VIBRATION_THRESHOLD:
            status = "WARNING"
        else:
            status = "RUNNING"

        self.sequence_number += 1

        return {
            "machine_id": self.machine_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "sequence_number": self.sequence_number,
            "temperature": temperature,
            "vibration": vibration,
            "status": status,
        }

    def publish_telemetry(self):
        topic = f"factory/{self.machine_id}/telemetry"

        while self.running:
            telemetry = self.generate_telemetry()
            payload = json.dumps(telemetry)

            result = self.client.publish(
                topic,
                payload=payload,
                qos=MQTT_QOS,
            )

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"[PUBLISHED] {topic}: {payload}")
            else:
                print(f"[ERROR] Failed to publish from {self.machine_id} (code: {result.rc})")

            # Sleep in small increments to allow responsive shutdown
            slept = 0.0
            while self.running and slept < PUBLISH_INTERVAL:
                time.sleep(min(0.2, PUBLISH_INTERVAL - slept))
                slept += 0.2

    def start(self):
        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.loop_start()

        # Publish online status after connecting.
        online_payload = json.dumps({
            "machine_id": self.machine_id,
            "status": "ONLINE",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        })

        self.client.publish(
            f"factory/{self.machine_id}/status",
            online_payload,
            qos=1,
            retain=True,
        )

        self.publish_telemetry()

    def stop(self):
        self.running = False

        # Publish OFFLINE before disconnecting normally.
        offline_payload = json.dumps({
            "machine_id": self.machine_id,
            "status": "OFFLINE",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "message": "Machine shut down normally",
        })

        self.client.publish(
            f"factory/{self.machine_id}/status",
            offline_payload,
            qos=1,
            retain=True,
        )

        self.client.disconnect()
        self.client.loop_stop()

        print(f"[STOPPED] {self.machine_id}")



def main():
    machines = []

    try:
        # Create all simulated machines.
        for i in range(1, MACHINE_COUNT + 1):
            machine_id = f"MACHINE_{i:02d}"
            machine = MachineSimulator(machine_id)
            machines.append(machine)

        # Connect every machine to the broker.
        for machine in machines:
            machine.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            machine.client.loop_start()

        # Wait briefly for connections to complete.
        time.sleep(2)

        # Publish online status and start one thread per machine.
        threads = []

        for machine in machines:
            online_payload = json.dumps({
                "machine_id": machine.machine_id,
                "status": "ONLINE",
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            })

            machine.client.publish(
                f"factory/{machine.machine_id}/status",
                online_payload,
                qos=1,
                retain=True,
            )

            thread = threading.Thread(
                target=machine.publish_telemetry
            )
            thread.start()
            threads.append(thread)

        # Keep the main program running.
        for thread in threads:
            thread.join()

    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping all machines...")

    finally:
        for machine in machines:
            if machine.client.is_connected():
                machine.stop()

        print("[SHUTDOWN] Simulator stopped.")


if __name__ == "__main__":
    main()

