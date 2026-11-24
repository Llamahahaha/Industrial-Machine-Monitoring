import React from 'react';

const statusColors = {
  NORMAL: '#22c55e',
  WARNING: '#f59e0b',
  CRITICAL: '#ef4444',
  OFFLINE: '#6b7280',
  'WAITING FOR DATA': '#94a3b8',
  connected: '#22c55e',
  disconnected: '#ef4444',
  error: '#ef4444',
};

export default function StatusBadge({ status, size = 'md' }) {
  const color = statusColors[status] || '#94a3b8';
  return (
    <span
      className={`status-badge status-badge-${size}`}
      style={{ backgroundColor: `${color}18`, color, borderColor: `${color}40` }}
    >
      <span className="status-dot" style={{ backgroundColor: color }} />
      {status || 'UNKNOWN'}
    </span>
  );
}
