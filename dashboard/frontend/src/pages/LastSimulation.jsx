import React, { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, BarChart, Bar, PieChart, Pie, Cell,
  ScatterChart, Scatter, AreaChart, Area
} from 'recharts';
import MetricCard from '../components/MetricCard';
import ExperimentSelector from '../components/ExperimentSelector';
import StatusBadge from '../components/StatusBadge';
import API from '../services/api';

const COLORS = { NORMAL: '#22c55e', WARNING: '#f59e0b', CRITICAL: '#ef4444' };

export default function LastSimulation() {
  const [experiments, setExperiments] = useState([]);
  const [selected, setSelected] = useState('');
  const [data, setData] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadInitial();
  }, []);

  const loadInitial = async () => {
    setLoading(true);
    try {
      const expList = await API.listExperiments();
      setExperiments(expList.experiments || []);

      // Auto-load latest
      try {
        const latest = await API.latestExperiment();
        if (latest.data) {
          setData(latest.data);
          setMetrics(latest.metrics);
          setSelected(latest.experiment.filename);
        }
      } catch (e) {
        // No experiments available
      }
    } catch (e) {
      setError('Failed to load experiments');
    }
    setLoading(false);
  };

  const loadExperiment = async (filename) => {
    setSelected(filename);
    if (!filename) { setData(null); setMetrics(null); return; }
    setLoading(true);
    setError(null);
    try {
      const [expData, expMetrics] = await Promise.all([
        API.getExperiment(filename),
        API.getExperimentMetrics(filename),
      ]);
      setData(expData.data);
      setMetrics(expMetrics.metrics);
    } catch (e) {
      setError(`Failed to load ${filename}`);
    }
    setLoading(false);
  };

  // Prepare chart data
  const messageTimeline = data?.messages?.map((m, i) => ({
    index: i,
    time: m.recv_time,
    machine_id: m.machine_id,
    seq: m.sequence_number,
    qos: m.qos,
    dup: m.dup_flag,
    alert: m.is_alert,
  })) || [];

  const latencyHistogram = (() => {
    if (!data?.latencies?.length) return [];
    const lats = data.latencies;
    const min = Math.floor(Math.min(...lats));
    const max = Math.ceil(Math.max(...lats));
    const binCount = Math.min(30, max - min + 1);
    const binWidth = (max - min) / binCount || 1;
    const bins = Array.from({ length: binCount }, (_, i) => ({
      range: `${(min + i * binWidth).toFixed(0)}`,
      count: 0,
    }));
    lats.forEach(l => {
      const idx = Math.min(Math.floor((l - min) / binWidth), binCount - 1);
      if (idx >= 0) bins[idx].count++;
    });
    return bins;
  })();

  const alertPieData = data ? [
    { name: 'Normal', value: data.total_normal || 0, color: COLORS.NORMAL },
    { name: 'Alert', value: data.total_alerts || 0, color: COLORS.CRITICAL },
  ].filter(d => d.value > 0) : [];

  const missingSeqData = data?.missing_sequences
    ? Object.entries(data.missing_sequences).map(([mid, seqs]) => ({
        machine: mid,
        missing: seqs.length,
      }))
    : [];

  const dupSeqData = data?.duplicate_sequences
    ? Object.entries(data.duplicate_sequences).map(([mid, count]) => ({
        machine: mid,
        duplicates: count,
      }))
    : [];

  return (
    <div className="page">
      <div className="page-header">
        <h2>Last Simulation</h2>
      </div>

      <ExperimentSelector experiments={experiments} selected={selected} onChange={loadExperiment} loading={false} />

      {error && <div className="error-banner">❌ {error}</div>}
      {loading && <div className="loading-state">⏳ Loading experiment data...</div>}

      {data && !loading && (
        <>
          {/* Experiment Info */}
          <div className="experiment-banner">
            <span>📄 {data.filename}</span>
            <span>🧪 QoS {data.qos} | Loss {data.loss_percent}% | Delay {data.delay_ms}ms</span>
            <span>📅 {new Date(data.modified * 1000).toLocaleString()}</span>
          </div>

          {/* Top Metrics */}
          <div className="metrics-grid">
            <MetricCard title="Total Messages" value={data.total_messages} icon="📨" color="#2563eb" />
            <MetricCard title="Duplicates" value={data.total_duplicates} icon="📋"
              color={data.total_duplicates > 0 ? '#f59e0b' : '#22c55e'} />
            <MetricCard title="Alerts" value={data.total_alerts} icon="🔔"
              color={data.total_alerts > 0 ? '#ef4444' : '#22c55e'} />
            {metrics && (
              <>
                <MetricCard title="Delivery Ratio"
                  value={metrics.delivery_ratio != null ? `${(metrics.delivery_ratio * 100).toFixed(1)}%` : '—'}
                  icon="📊" color="#2563eb" />
                <MetricCard title="Avg Latency"
                  value={metrics.avg_latency_ms != null ? `${metrics.avg_latency_ms.toFixed(1)} ms` : '—'}
                  icon="⏱️" color="#2563eb" />
                <MetricCard title="Throughput"
                  value={metrics.throughput_msg_s != null ? `${metrics.throughput_msg_s.toFixed(2)} msg/s` : '—'}
                  icon="🚀" color="#2563eb" />
              </>
            )}
          </div>

          {/* Temperature / Vibration notice */}
          {!data.has_temperature && (
            <div className="info-banner">
              ℹ️ Temperature and vibration graphs require additional telemetry columns in the CSV.
              The current CSV schema (recv_time, topic, machine_id, sequence_number, timestamp, qos, dup_flag, is_alert, payload_bytes)
              does not include temperature or vibration values.
            </div>
          )}

          {/* Charts Grid */}
          <div className="charts-grid">
            {/* Message Reception Over Time */}
            <div className="chart-container">
              <h3 className="chart-title">Message Reception Over Time</h3>
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={data.throughput || []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="time" tick={{ fontSize: 10 }} tickFormatter={v => ''} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Area type="monotone" dataKey="messages" fill="#2563eb22" stroke="#2563eb" />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Latency Distribution */}
            {latencyHistogram.length > 0 && (
              <div className="chart-container">
                <h3 className="chart-title">Latency Distribution (ms)</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={latencyHistogram}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="range" tick={{ fontSize: 10 }} label={{ value: 'ms', position: 'insideBottomRight' }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#2563eb" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Missing Sequences */}
            {missingSeqData.length > 0 && (
              <div className="chart-container">
                <h3 className="chart-title">Missing Sequences by Machine</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={missingSeqData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="machine" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="missing" fill="#ef4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Duplicate Messages */}
            {dupSeqData.some(d => d.duplicates > 0) && (
              <div className="chart-container">
                <h3 className="chart-title">Duplicate Messages by Machine</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={dupSeqData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="machine" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="duplicates" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Alert Distribution */}
            {alertPieData.length > 0 && (
              <div className="chart-container">
                <h3 className="chart-title">Alert Distribution</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <PieChart>
                    <Pie data={alertPieData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                      outerRadius={100} label={({ name, value }) => `${name}: ${value}`}>
                      {alertPieData.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Throughput Over Time */}
            {data.throughput?.length > 0 && (
              <div className="chart-container">
                <h3 className="chart-title">Throughput Over Time</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={data.throughput}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="time" tick={{ fontSize: 10 }} tickFormatter={v => ''} />
                    <YAxis tick={{ fontSize: 11 }} label={{ value: 'msg/bin', angle: -90, position: 'insideLeft' }} />
                    <Tooltip />
                    <Line type="monotone" dataKey="messages" stroke="#4CAF50" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </>
      )}

      {!data && !loading && !error && (
        <div className="empty-state">
          <p>🧪 No simulation data available</p>
          <p className="empty-hint">Run a monitoring experiment to generate data, or select an experiment above</p>
        </div>
      )}
    </div>
  );
}
