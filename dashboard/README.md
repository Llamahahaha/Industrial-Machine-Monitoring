# Industrial Machine Monitoring Dashboard

A LAN-accessible web dashboard for the Industrial Machine Monitoring System.

## Quick Start

### 1. Start the Backend (Terminal 1)

```powershell
cd C:\Users\parab\OneDrive\Desktop\Industrial-Machine-Monitoring\dashboard\backend
..\..\\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2. Start the Frontend (Terminal 2)

```powershell
cd C:\Users\parab\OneDrive\Desktop\Industrial-Machine-Monitoring\dashboard\frontend
pnpm run dev -- --host 0.0.0.0
```

### 3. Open the Dashboard

Open your browser and go to: **http://localhost:5173**

### 4. (Optional) Start Monitoring (Terminal 3)

```powershell
cd C:\Users\parab\OneDrive\Desktop\Industrial-Machine-Monitoring
.\.venv\Scripts\python.exe monitoring\monitor.py --qos 1 --loss 10 --delay 100 --overwrite
```

## LAN Access

To access from another device on the same network:

1. Find your IP address:
   ```powershell
   ipconfig
   ```
   Look for your Wi-Fi or Ethernet IPv4 address (e.g., `192.168.1.100`).

2. Open the dashboard from another device:
   ```
   http://YOUR_IP:5173
   ```

3. **Windows Firewall**: Allow ports 5173 and 8000 through the firewall:
   ```powershell
   netsh advfirewall firewall add rule name="Dashboard Frontend" dir=in action=allow protocol=TCP localport=5173
   netsh advfirewall firewall add rule name="Dashboard Backend" dir=in action=allow protocol=TCP localport=8000
   ```

## Architecture

```
MQTT Broker → monitor.py → alert_system.py → CSV Log
                                           → FastAPI Backend → WebSocket → React Dashboard
```

## Tabs

- **Live Monitoring**: Real-time machine telemetry via WebSocket
- **Analysis**: Experiment metrics from CSV files
- **Last Simulation**: Auto-loads the latest experiment with interactive graphs
