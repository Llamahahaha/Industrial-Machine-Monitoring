import React from 'react';

const navItems = [
  { id: 'live', label: 'Live Monitoring', icon: '📡' },
  { id: 'analysis', label: 'Analysis', icon: '📊' },
  { id: 'simulation', label: 'Last Simulation', icon: '🧪' },
];

export default function Sidebar({ activeTab, onTabChange }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">🏭</div>
        <h1 className="sidebar-title">INDUSTRIAL MACHINE MONITORING</h1>
      </div>
      <nav className="sidebar-nav">
        {navItems.map(item => (
          <button
            key={item.id}
            className={`nav-item ${activeTab === item.id ? 'active' : ''}`}
            onClick={() => onTabChange(item.id)}
          >
            <span className="nav-icon">{item.icon}</span>
            <span className="nav-label">{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="version">v1.0.0</span>
      </div>
    </aside>
  );
}
