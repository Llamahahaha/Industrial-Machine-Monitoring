import React from 'react';

export default function MetricCard({ title, value, subtitle, color, icon }) {
  return (
    <div className="metric-card" style={{ borderTopColor: color || '#2563eb' }}>
      <div className="metric-header">
        <span className="metric-icon">{icon}</span>
        <span className="metric-title">{title}</span>
      </div>
      <div className="metric-value" style={{ color: color || '#1a2332' }}>
        {value ?? '—'}
      </div>
      {subtitle && <div className="metric-subtitle">{subtitle}</div>}
    </div>
  );
}
