import React from 'react';

export default function ExperimentSelector({ experiments = [], selected, onChange, loading }) {
  if (loading) {
    return <div className="selector-loading">Loading experiments...</div>;
  }

  if (experiments.length === 0) {
    return (
      <div className="empty-state">
        <p>📂 No experiment files found</p>
        <p className="empty-hint">Run a monitoring experiment to generate CSV data</p>
      </div>
    );
  }

  return (
    <div className="experiment-selector">
      <label className="selector-label">Select Experiment:</label>
      <select
        className="selector-dropdown"
        value={selected || ''}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">— Choose an experiment —</option>
        {experiments.map(exp => (
          <option key={exp.filename} value={exp.filename}>
            {exp.filename}
            {exp.qos != null ? ` (QoS ${exp.qos}, Loss ${exp.loss_percent}%, Delay ${exp.delay_ms}ms)` : ''}
          </option>
        ))}
      </select>
    </div>
  );
}
