import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import LiveMonitoring from './pages/LiveMonitoring';
import Analysis from './pages/Analysis';
import LastSimulation from './pages/LastSimulation';

export default function App() {
  const [activeTab, setActiveTab] = useState('live');

  const renderPage = () => {
    switch (activeTab) {
      case 'live': return <LiveMonitoring />;
      case 'analysis': return <Analysis />;
      case 'simulation': return <LastSimulation />;
      default: return <LiveMonitoring />;
    }
  };

  return (
    <div className="app-layout">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />
      <main className="main-content">
        {renderPage()}
      </main>
    </div>
  );
}
