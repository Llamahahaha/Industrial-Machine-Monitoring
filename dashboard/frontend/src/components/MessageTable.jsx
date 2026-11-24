import React from 'react';
import StatusBadge from './StatusBadge';

export default function MessageTable({ messages = [], maxRows = 50 }) {
  const displayed = messages.slice(-maxRows).reverse();

  if (displayed.length === 0) {
    return (
      <div className="empty-state">
        <p>📭 No messages received yet</p>
        <p className="empty-hint">Messages will appear here when the monitoring system is active</p>
      </div>
    );
  }

  return (
    <div className="table-container">
      <table className="data-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Machine</th>
            <th>Seq #</th>
            <th>QoS</th>
            <th>DUP</th>
            <th>Alert</th>
            <th>Topic</th>
          </tr>
        </thead>
        <tbody>
          {displayed.map((msg, i) => (
            <tr key={i} className={msg.is_alert ? 'row-alert' : ''}>
              <td className="cell-mono">{msg.recv_time ? new Date(msg.recv_time).toLocaleTimeString() : '—'}</td>
              <td className="cell-bold">{msg.machine_id || '—'}</td>
              <td className="cell-mono">{msg.sequence_number ?? '—'}</td>
              <td>{msg.qos ?? '—'}</td>
              <td>{msg.dup_flag ? '⚠️ Yes' : 'No'}</td>
              <td><StatusBadge status={msg.alert_level || (msg.is_alert ? 'WARNING' : 'NORMAL')} size="sm" /></td>
              <td className="cell-topic">{msg.topic || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
