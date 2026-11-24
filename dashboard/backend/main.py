"""FastAPI application for the Industrial Machine Monitoring Dashboard."""

import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Add backend dir to path for local imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from websocket_manager import manager
from routers import monitoring, experiments


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    print("🚀 Dashboard backend starting...")
    print(f"📁 Monitoring logs: {Path(__file__).resolve().parent.parent.parent / 'monitoring' / 'logs'}")
    yield
    print("👋 Dashboard backend shutting down...")


app = FastAPI(
    title="Industrial Machine Monitoring Dashboard",
    description="Backend API for the MQTT monitoring dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - allow dashboard frontend from any origin on LAN
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(monitoring.router)
app.include_router(experiments.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "Industrial Machine Monitoring Dashboard"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for live telemetry streaming."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            # Echo back as heartbeat
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
