import React from 'react';
import StatusBadge from './StatusBadge';

export default function MachineCard({ machine }) {
  if (!machine) return null;
  const { machine_id, temperature, vibration, status, alert_level, recv_time } = machine;

  return (
    <div className={`machine-card machine-card-${(alert_level || 'NORMAL').toLowerCase()}`}>
      <div className="machine-card-header">
        <h3 className="machine-id">{machine_id}</h3>
        <StatusBadge status={alert_level || 'NORMAL'} />
      </div>
      <div className="machine-card-body">
        <div className="machine-metric">
          <span className="metric-label">🌡️ Temperature</span>
          <span className="metric-val">{temperature != null ? `${temperature}°C` : '—'}</span>
        </div>
        <div className="machine-metric">
          <span className="metric-label">📳 Vibration</span>
          <span className="metric-val">{vibration != null ? `${vibration}g` : '—'}</span>
        </div>
        <div className="machine-metric">
          <span className="metric-label">⚙️ Status</span>
          <span className="metric-val">{status || 'UNKNOWN'}</span>
        </div>
      </div>
      {recv_time && (
        <div className="machine-card-footer">
          Last: {new Date(recv_time).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
