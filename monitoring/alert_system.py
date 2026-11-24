# alert_system.py
"""Alert system for the Industrial Machine Monitoring project.

This module contains pure Python logic for evaluating telemetry data
(e.g., temperature and vibration) and turning it into human‑readable
alerts.  It does **not** talk to MQTT – the subscriber (monitor.py) can
import these functions and call them whenever a new message arrives.

The design is deliberately simple so beginners can see how the pieces
fit together:

* `process_telemetry(payload: dict)` – main entry point that receives a
  JSON‑decoded dictionary from the MQTT subscriber.
* `handle_last_will(payload: dict)` – processes a special *Last Will*
  message that tells us a machine has gone offline.
* Helper functions `check_temperature` and `check_vibration` generate
  warnings or critical alerts based on the thresholds you specified.
"""

from typing import Dict, Any

# ---------------------------------------------------------------------------
# Configuration – thresholds for alerts.  Adjust as needed.
# ---------------------------------------------------------------------------
TEMP_WARNING = 80.0   # °C – generate a *warning* if temperature > this
TEMP_CRITICAL = 90.0  # °C – generate a *critical* alert if > this
VIB_WARNING = 5.0     # mm/s – warning threshold
VIB_CRITICAL = 7.0    # mm/s – critical threshold

# ---------------------------------------------------------------------------
# Helper functions that print alerts.  Keeping the printing logic here makes
# it easy to replace later with logging, UI pop‑ups, etc.
# ---------------------------------------------------------------------------

def _alert(level: str, machine_id: str, metric: str, value: Any) -> None:
    """Print an alert.

    Parameters
    ----------
    level: str
        Either "WARNING" or "CRITICAL".
    machine_id: str
        Identifier of the machine that generated the abnormal reading.
    metric: str
        Name of the metric (e.g., "temperature").
    value: Any
        The out‑of‑range value.
    """
    print(f"[🔔 {level}] Machine {machine_id}: {metric} = {value}")


def check_temperature(machine_id: str, temperature: float) -> None:
    """Generate alerts based on temperature thresholds.

    - > TEMP_WARNING → *warning*
    - > TEMP_CRITICAL → *critical*
    """
    if temperature > TEMP_CRITICAL:
        _alert("CRITICAL", machine_id, "temperature", f"{temperature}°C")
    elif temperature > TEMP_WARNING:
        _alert("WARNING", machine_id, "temperature", f"{temperature}°C")
    # Values at or below the warning threshold are considered normal.


def check_vibration(machine_id: str, vibration: float) -> None:
    """Generate alerts based on vibration thresholds (mm/s)."""
    if vibration > VIB_CRITICAL:
        _alert("CRITICAL", machine_id, "vibration", f"{vibration} mm/s")
    elif vibration > VIB_WARNING:
        _alert("WARNING", machine_id, "vibration", f"{vibration} mm/s")

# ---------------------------------------------------------------------------
# Public API – functions that the MQTT subscriber can call.
# ---------------------------------------------------------------------------

def process_telemetry(payload: Dict[str, Any]) -> None:
    """Evaluate a telemetry reading and emit alerts if needed.

    The `payload` argument should be a dictionary that matches the JSON
    format used by the machines, for example::

        {
            "machine_id": "MACHINE_01",
            "timestamp": "2026-11-24T16:30:00Z",
            "sequence_number": 42,
            "temperature": 76.5,
            "vibration": 4.2,
            "status": "RUNNING"
        }

    Only the `machine_id`, `temperature`, and `vibration` fields are
    inspected for alerts; the other fields are ignored by this module.
    """
    machine_id = payload.get("machine_id", "unknown")
    temperature = payload.get("temperature")
    vibration = payload.get("vibration")

    # Guard against missing values – we simply skip the check.
    if isinstance(temperature, (int, float)):
        check_temperature(machine_id, float(temperature))
    if isinstance(vibration, (int, float)):
        check_vibration(machine_id, float(vibration))


def handle_last_will(payload: Dict[str, Any]) -> None:
    """Handle an MQTT *Last Will* message indicating a machine went offline.

    A typical Last Will payload might look like::

        {"machine_id": "MACHINE_03", "status": "OFFLINE"}

    This function prints a clear notification so the operator knows the
    machine stopped sending data.
    """
    machine_id = payload.get("machine_id", "unknown")
    status = payload.get("status", "UNKNOWN")
    if status.upper() == "OFFLINE":
        print(f"[⚠️ OFFLINE] Machine {machine_id} has stopped publishing data.")
    else:
        # If the payload is something else we just display it for debugging.
        print(f"[ℹ️] Last Will from {machine_id}: {payload}")


# ---------------------------------------------------------------------------
# Public API – functions that the MQTT subscriber can call.
# ---------------------------------------------------------------------------

def evaluate_alert(machine_id: str, temperature: float | None, vibration: float | None) -> str:
    """Return the overall alert level for a machine.

    Returns one of:
    * "CRITICAL" – any reading exceeds its critical threshold.
    * "WARNING"  – any reading exceeds its warning threshold (but not critical).
    * "NORMAL"   – all present readings are within normal limits.
    * "WAITING FOR DATA" – no temperature or vibration provided.
    """
    # If both readings are missing, we are still waiting for data.
    if temperature is None and vibration is None:
        return "WAITING FOR DATA"

    # Determine severity for each metric independently.
    temp_sev = "NORMAL"
    vib_sev = "NORMAL"
    if isinstance(temperature, (int, float)):
        if temperature > TEMP_CRITICAL:
            temp_sev = "CRITICAL"
        elif temperature > TEMP_WARNING:
            temp_sev = "WARNING"
    if isinstance(vibration, (int, float)):
        if vibration > VIB_CRITICAL:
            vib_sev = "CRITICAL"
        elif vibration > VIB_WARNING:
            vib_sev = "WARNING"

    # Combine severities – CRITICAL wins, then WARNING.
    if "CRITICAL" in (temp_sev, vib_sev):
        return "CRITICAL"
    if "WARNING" in (temp_sev, vib_sev):
        return "WARNING"
    return "NORMAL"

def process_telemetry(payload: Dict[str, Any]) -> None:
    """Evaluate a telemetry reading and emit alerts if needed.

    The `payload` argument should be a dictionary that matches the JSON
    format used by the machines, for example::

        {
            "machine_id": "MACHINE_01",
            "timestamp": "2026-11-24T16:30:00Z",
            "sequence_number": 42,
            "temperature": 76.5,
            "vibration": 4.2,
            "status": "RUNNING"
        }

    Only the `machine_id`, `temperature`, and `vibration` fields are inspected for alerts; the other fields are ignored by this module.
    """
    machine_id = payload.get("machine_id", "unknown")
    temperature = payload.get("temperature")
    vibration = payload.get("vibration")

    # Guard against missing values – we simply skip the check.
    if isinstance(temperature, (int, float)):
        check_temperature(machine_id, float(temperature))
    if isinstance(vibration, (int, float)):
        check_vibration(machine_id, float(vibration))

    # Also print a concise status using the central evaluation function.
    alert_level = evaluate_alert(machine_id, temperature, vibration)
    print(f"[📊] Machine {machine_id}: Temp={temperature}°C, Vib={vibration}g → {alert_level}")

# Export the public symbols for easier imports.
__all__ = ["process_telemetry", "handle_last_will", "evaluate_alert"]

