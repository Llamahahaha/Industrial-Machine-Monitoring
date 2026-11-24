import React from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, ReferenceLine
} from 'recharts';

export default function LiveChart({ data = [], title, dataKey, color = '#2563eb', unit = '', warningThreshold, criticalThreshold }) {
  if (data.length === 0) {
    return (
      <div className="chart-container">
        <h3 className="chart-title">{title}</h3>
        <div className="empty-state">
          <p>📈 Waiting for data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chart-container">
      <h3 className="chart-title">{title}</h3>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="time"
            tick={{ fontSize: 11, fill: '#6b7280' }}
            tickFormatter={(v) => v ? new Date(v).toLocaleTimeString() : ''}
          />
          <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} unit={unit} />
          <Tooltip
            labelFormatter={(v) => v ? new Date(v).toLocaleString() : ''}
            formatter={(v) => [`${v}${unit}`, dataKey]}
          />
          <Legend />
          {warningThreshold && (
            <ReferenceLine y={warningThreshold} stroke="#f59e0b" strokeDasharray="5 5" label="Warning" />
          )}
          {criticalThreshold && (
            <ReferenceLine y={criticalThreshold} stroke="#ef4444" strokeDasharray="5 5" label="Critical" />
          )}
          <Line
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
