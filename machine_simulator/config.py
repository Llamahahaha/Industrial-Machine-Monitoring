import os
from dotenv import load_dotenv

# Load environment variables from the project's .env file
load_dotenv()

# MQTT broker configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

# Machine simulator configuration
MACHINE_COUNT = int(os.getenv("MACHINE_COUNT", "5"))
PUBLISH_INTERVAL = float(os.getenv("PUBLISH_INTERVAL", "2"))

# MQTT Quality of Service: 0, 1, or 2
MQTT_QOS = int(os.getenv("MQTT_QOS", "1"))

# Telemetry thresholds
TEMPERATURE_THRESHOLD = 80.0
VIBRATION_THRESHOLD = 8.0

# Validate configuration
if not 1 <= MACHINE_COUNT <= 10:
    raise ValueError("MACHINE_COUNT must be between 1 and 10")

if MQTT_QOS not in (0, 1, 2):
    raise ValueError("MQTT_QOS must be 0, 1, or 2")

if PUBLISH_INTERVAL <= 0:
    raise ValueError("PUBLISH_INTERVAL must be greater than zero")

if not MQTT_USERNAME or not MQTT_PASSWORD:
    raise ValueError("MQTT username and password must be set in .env")
