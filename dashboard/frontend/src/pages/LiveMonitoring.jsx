import React, { useState, useEffect, useRef } from 'react';
import MetricCard from '../components/MetricCard';
import MachineCard from '../components/MachineCard';
import MessageTable from '../components/MessageTable';
import LiveChart from '../components/LiveChart';
import StatusBadge from '../components/StatusBadge';
import { LiveWebSocket, API } from '../services/api';

const MAX_CHART_POINTS = 100;

export default function LiveMonitoring() {
  const [wsStatus, setWsStatus] = useState('disconnected');
  const [machines, setMachines] = useState({});
  const [stats, setStats] = useState({
    total_messages: 0, total_alerts: 0, monitoring_active: false,
    broker_connected: false, last_message_time: null,
    experiment: { qos: null, loss: null, delay: null },
  });
  const [messages, setMessages] = useState([]);
  const [tempData, setTempData] = useState([]);
  const [vibData, setVibData] = useState([]);
  const wsRef = useRef(null);

  useEffect(() => {
    // Initial fetch
    API.monitoringStatus()
      .then(data => {
        if (data.machines) setMachines(data.machines);
        if (data.stats) setStats(data.stats);
      })
      .catch(() => {});

    // WebSocket connection
    const ws = new LiveWebSocket(
      (msg) => {
        if (msg.type === 'init') {
          if (msg.machines) setMachines(msg.machines);
          if (msg.stats) setStats(msg.stats);
        } else if (msg.type === 'telemetry') {
          const d = msg.data;
          setMachines(prev => ({ ...prev, [d.machine_id]: d }));
          setStats(prev => ({
            ...prev,
            total_messages: prev.total_messages + 1,
            total_alerts: prev.total_alerts + (d.is_alert ? 1 : 0),
            last_message_time: d.recv_time,
            monitoring_active: true,
            broker_connected: true,
          }));
          setMessages(prev => [...prev.slice(-199), d]);

          // Update charts
          const point = { time: d.recv_time, machine: d.machine_id };
          if (d.temperature != null) {
            setTempData(prev => [...prev.slice(-(MAX_CHART_POINTS - 1)), { ...point, temperature: d.temperature }]);
          }
          if (d.vibration != null) {
            setVibData(prev => [...prev.slice(-(MAX_CHART_POINTS - 1)), { ...point, vibration: d.vibration }]);
          }
        } else if (msg.type === 'status') {
          if (msg.data) setStats(msg.data);
        }
      },
      (status) => setWsStatus(status)
    );
    wsRef.current = ws;

    return () => ws.close();
  }, []);

  const machineList = Object.values(machines);
  const exp = stats.experiment || {};

  return (
    <div className="page">
      <div className="page-header">
        <h2>Live Monitoring</h2>
        <StatusBadge status={wsStatus} />
      </div>

      {/* Experiment Parameters */}
      {exp.qos != null && (
        <div className="experiment-banner">
          <span>🧪 Experiment: QoS {exp.qos} | Loss {exp.loss}% | Delay {exp.delay}ms</span>
        </div>
      )}

      {/* Top Metrics */}
      <div className="metrics-grid">
        <MetricCard title="Broker" value={stats.broker_connected ? 'Connected' : 'Disconnected'}
          color={stats.broker_connected ? '#22c55e' : '#ef4444'} icon="🔗" />
        <MetricCard title="Monitor" value={stats.monitoring_active ? 'Active' : 'Inactive'}
          color={stats.monitoring_active ? '#22c55e' : '#6b7280'} icon="📡" />
        <MetricCard title="Active Machines" value={machineList.length}
          color="#2563eb" icon="🏭" />
        <MetricCard title="Messages" value={stats.total_messages}
          color="#2563eb" icon="📨" />
        <MetricCard title="Alerts" value={stats.total_alerts}
          color={stats.total_alerts > 0 ? '#ef4444' : '#22c55e'} icon="🔔" />
        <MetricCard title="Last Message"
          value={stats.last_message_time ? new Date(stats.last_message_time).toLocaleTimeString() : '—'}
          color="#6b7280" icon="🕐" />
      </div>

      {/* Machine Cards */}
      {machineList.length > 0 ? (
        <div className="section">
          <h3 className="section-title">Machine Status</h3>
          <div className="machines-grid">
            {machineList.map(m => (
              <MachineCard key={m.machine_id} machine={m} />
            ))}
          </div>
        </div>
      ) : (
        <div className="empty-state">
          <p>🏭 No machines detected</p>
          <p className="empty-hint">Start the monitoring system and machine simulator to see live data</p>
        </div>
      )}

      {/* Live Charts */}
      <div className="charts-row">
        <LiveChart data={tempData} title="Temperature vs Time" dataKey="temperature"
          color="#ef4444" unit="°C" warningThreshold={80} criticalThreshold={90} />
        <LiveChart data={vibData} title="Vibration vs Time" dataKey="vibration"
          color="#2563eb" unit="g" warningThreshold={5} criticalThreshold={7} />
      </div>

      {/* Message Table */}
      <div className="section">
        <h3 className="section-title">Recent Messages</h3>
        <MessageTable messages={messages} />
      </div>
    </div>
  );
}
