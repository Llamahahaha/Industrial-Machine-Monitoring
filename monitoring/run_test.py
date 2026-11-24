# run_test.py
"""Run integration tests for the alert system and monitor integration.
We directly import alert_system and simulate MQTT payload handling.
"""

from alert_system import evaluate_alert, process_telemetry, handle_last_will

samples = [
    {"machine_id": "M01", "temperature": 65, "vibration": 2, "expected": "NORMAL"},
    {"machine_id": "M02", "temperature": 85, "vibration": 3, "expected": "WARNING"},
    {"machine_id": "M03", "temperature": 95, "vibration": 2, "expected": "CRITICAL"},
    {"machine_id": "M04", "temperature": 65, "vibration": 6, "expected": "WARNING"},
    {"machine_id": "M05", "temperature": 65, "vibration": 8, "expected": "CRITICAL"},
    {"machine_id": "M06", "temperature": 95, "vibration": 8, "expected": "CRITICAL"},
]

print("--- Evaluating alerts ---")
for s in samples:
    level = evaluate_alert(s["machine_id"], s["temperature"], s["vibration"])
    status = "PASS" if level == s["expected"] else f"FAIL (got {level})"
    print(f"{s['machine_id']}: expected {s['expected']}, got {level} -> {status}")

print("\n--- Testing process_telemetry output (should print concise status) ---")
process_telemetry({"machine_id": "M01", "temperature": 85, "vibration": 6})
process_telemetry({"machine_id": "M02", "temperature": 95, "vibration": 2})
process_telemetry({"machine_id": "M03", "temperature": 65, "vibration": 2})
process_telemetry({"machine_id": "M04"})  # missing values

print("\n--- Testing Last Will handling ---")
handle_last_will({"machine_id": "M05", "status": "OFFLINE"})
