import React, { useState, useEffect } from 'react';
import MetricCard from '../components/MetricCard';
import ExperimentSelector from '../components/ExperimentSelector';
import API from '../services/api';

export default function Analysis() {
  const [experiments, setExperiments] = useState([]);
  const [selected, setSelected] = useState('');
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [source, setSource] = useState('');
  const [error, setError] = useState(null);

  useEffect(() => {
    loadExperiments();
  }, [source]);

  const loadExperiments = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await API.listExperiments(source || undefined);
      setExperiments(data.experiments || []);
    } catch (e) {
      setError('Failed to load experiments');
    }
    setLoading(false);
  };

  const loadMetrics = async (filename) => {
    setSelected(filename);
    if (!filename) { setMetrics(null); return; }
    setMetricsLoading(true);
    setError(null);
    try {
      const data = await API.getExperimentMetrics(filename, source || undefined);
      setMetrics(data.metrics);
    } catch (e) {
      setError(`Failed to load metrics for ${filename}`);
      setMetrics(null);
    }
    setMetricsLoading(false);
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Experiment Analysis</h2>
      </div>

      {/* Source toggle */}
      <div className="filter-bar">
        <label className="filter-label">Data Source:</label>
        <select className="selector-dropdown" value={source} onChange={e => { setSource(e.target.value); setSelected(''); setMetrics(null); }}>
          <option value="">Monitoring Logs</option>
          <option value="sample">Sample Data</option>
        </select>
      </div>

      <ExperimentSelector experiments={experiments} selected={selected} onChange={loadMetrics} loading={loading} />

      {error && <div className="error-banner">❌ {error}</div>}

      {metricsLoading && <div className="loading-state">⏳ Computing metrics...</div>}

      {metrics && !metricsLoading && (
        <div className="analysis-results">
          <h3 className="section-title">Metrics for {selected}</h3>
          <div className="metrics-grid">
            <MetricCard title="Sent" value={metrics.sent} icon="📤" color="#2563eb" />
            <MetricCard title="Received (Unique)" value={metrics.received_unique} icon="📥" color="#22c55e" />
            <MetricCard title="Lost" value={metrics.lost} icon="❌" color="#ef4444" />
            <MetricCard title="Delivery Ratio" value={metrics.delivery_ratio != null ? `${(metrics.delivery_ratio * 100).toFixed(1)}%` : '—'} icon="📊" color="#2563eb" />
            <MetricCard title="Duplicates" value={metrics.duplicates} icon="📋"
              color={metrics.duplicates > 0 ? '#f59e0b' : '#22c55e'}
              subtitle={metrics.dup_rate != null ? `${(metrics.dup_rate * 100).toFixed(1)}% rate` : ''} />
            <MetricCard title="Avg Latency" value={metrics.avg_latency_ms != null ? `${metrics.avg_latency_ms.toFixed(1)} ms` : '—'} icon="⏱️" color="#2563eb" />
            <MetricCard title="Median Latency" value={metrics.median_latency_ms != null ? `${metrics.median_latency_ms.toFixed(1)} ms` : '—'} icon="⏱️" color="#6b7280" />
            <MetricCard title="P95 Latency" value={metrics.p95_latency_ms != null ? `${metrics.p95_latency_ms.toFixed(1)} ms` : '—'} icon="⏱️" color="#f59e0b" />
            <MetricCard title="Max Latency" value={metrics.max_latency_ms != null ? `${metrics.max_latency_ms.toFixed(1)} ms` : '—'} icon="⏱️" color="#ef4444" />
            <MetricCard title="Throughput" value={metrics.throughput_msg_s != null ? `${metrics.throughput_msg_s.toFixed(2)} msg/s` : '—'} icon="🚀" color="#2563eb" />
            <MetricCard title="Alerts Sent" value={metrics.alerts_sent} icon="🔔" color="#f59e0b" />
            <MetricCard title="Alerts Received" value={metrics.alerts_received} icon="🔔" color="#22c55e" />
          </div>

          {/* Experiment info */}
          <div className="experiment-info">
            <h4>Configuration</h4>
            <div className="info-grid">
              <span>QoS: <strong>{metrics.qos}</strong></span>
              <span>Packet Loss: <strong>{metrics.loss_percent}%</strong></span>
              <span>Network Delay: <strong>{metrics.delay_ms} ms</strong></span>
            </div>
          </div>
        </div>
      )}

      {!selected && !loading && experiments.length > 0 && (
        <div className="empty-state">
          <p>📊 Select an experiment above to view its metrics</p>
        </div>
      )}
    </div>
  );
}
