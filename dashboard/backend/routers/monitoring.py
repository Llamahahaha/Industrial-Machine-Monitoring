"""Live monitoring routes and WebSocket endpoint."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, Any

from websocket_manager import manager

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


class TelemetryEvent(BaseModel):
    """Telemetry event pushed by monitor.py."""
    recv_time: str
    topic: str = ""
    machine_id: str = "unknown"
    sequence_number: Optional[Any] = None
    timestamp: Optional[str] = None
    qos: Optional[int] = None
    dup_flag: Optional[int] = 0
    is_alert: Optional[int] = 0
    payload_bytes: Optional[int] = 0
    temperature: Optional[float] = None
    vibration: Optional[float] = None
    status: Optional[str] = "RUNNING"
    alert_level: Optional[str] = "NORMAL"


class MonitoringStatusUpdate(BaseModel):
    """Status update from monitor.py (connect/disconnect)."""
    monitoring_active: bool
    broker_connected: bool = False
    qos: Optional[int] = None
    loss: Optional[int] = None
    delay: Optional[int] = None


@router.post("/event")
async def receive_telemetry_event(event: TelemetryEvent):
    """Receive a telemetry event from monitor.py and broadcast to WebSocket clients."""
    data = event.model_dump()
    manager.update_from_telemetry(data)
    await manager.broadcast({"type": "telemetry", "data": data})
    return {"status": "ok"}


@router.post("/status")
async def update_monitoring_status(update: MonitoringStatusUpdate):
    """Receive monitoring status update from monitor.py."""
    manager.set_monitoring_status(update.monitoring_active, update.broker_connected)
    if update.qos is not None:
        manager.update_experiment(update.qos, update.loss, update.delay)
    await manager.broadcast({"type": "status", "data": manager.stats})
    return {"status": "ok"}


@router.get("/status")
async def get_monitoring_status():
    """Get current monitoring status."""
    return {
        "stats": manager.stats,
        "active_machines": len(manager.machines),
        "machines": manager.machines,
    }


@router.get("/latest")
async def get_latest_messages():
    """Get current machine states."""
    return {"machines": manager.machines, "stats": manager.stats}


@router.get("/messages")
async def get_recent_messages():
    """Get machine states as a list."""
    return {"machines": list(manager.machines.values()), "stats": manager.stats}
