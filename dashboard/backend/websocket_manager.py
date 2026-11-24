"""WebSocket connection manager for broadcasting live telemetry to React dashboard."""

import asyncio
import json
from typing import Dict, Any
from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and broadcasts messages to all connected clients."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        # Store latest state for new clients
        self.machines: Dict[str, Dict[str, Any]] = {}
        self.stats = {
            "total_messages": 0,
            "total_alerts": 0,
            "monitoring_active": False,
            "broker_connected": False,
            "last_message_time": None,
            "experiment": {"qos": None, "loss": None, "delay": None},
        }

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send current state to new client
        await websocket.send_json({
            "type": "init",
            "machines": self.machines,
            "stats": self.stats,
        })

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Send message to all connected WebSocket clients."""
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    def update_from_telemetry(self, data: dict):
        """Update internal state from a telemetry event pushed by monitor.py."""
        machine_id = data.get("machine_id", "unknown")
        self.machines[machine_id] = {
            "machine_id": machine_id,
            "temperature": data.get("temperature"),
            "vibration": data.get("vibration"),
            "status": data.get("status", "RUNNING"),
            "alert_level": data.get("alert_level", "NORMAL"),
            "timestamp": data.get("timestamp"),
            "recv_time": data.get("recv_time"),
            "sequence_number": data.get("sequence_number"),
            "qos": data.get("qos"),
            "dup_flag": data.get("dup_flag"),
            "topic": data.get("topic"),
        }
        self.stats["total_messages"] += 1
        if data.get("is_alert"):
            self.stats["total_alerts"] += 1
        self.stats["last_message_time"] = data.get("recv_time")
        self.stats["monitoring_active"] = True
        self.stats["broker_connected"] = True

    def update_experiment(self, qos, loss, delay):
        self.stats["experiment"] = {"qos": qos, "loss": loss, "delay": delay}

    def set_monitoring_status(self, active: bool, broker_connected: bool = None):
        self.stats["monitoring_active"] = active
        if broker_connected is not None:
            self.stats["broker_connected"] = broker_connected


manager = ConnectionManager()
