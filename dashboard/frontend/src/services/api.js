// Auto-detect API base URL for LAN access
const getApiBase = () => {
  const host = window.location.hostname || 'localhost';
  return `http://${host}:8000`;
};

const API_BASE = getApiBase();
const WS_BASE = API_BASE.replace('http', 'ws');

export const API = {
  health: () => fetch(`${API_BASE}/api/health`).then(r => r.json()),
  
  // Monitoring
  monitoringStatus: () => fetch(`${API_BASE}/api/monitoring/status`).then(r => r.json()),
  monitoringLatest: () => fetch(`${API_BASE}/api/monitoring/latest`).then(r => r.json()),
  
  // Experiments
  listExperiments: (source) => {
    const params = source ? `?source=${source}` : '';
    return fetch(`${API_BASE}/api/experiments${params}`).then(r => r.json());
  },
  latestExperiment: (source) => {
    const params = source ? `?source=${source}` : '';
    return fetch(`${API_BASE}/api/experiments/latest${params}`).then(r => r.json());
  },
  getExperiment: (filename, source) => {
    const params = source ? `?source=${source}` : '';
    return fetch(`${API_BASE}/api/experiments/${filename}${params}`).then(r => r.json());
  },
  getExperimentMetrics: (filename, source) => {
    const params = source ? `?source=${source}` : '';
    return fetch(`${API_BASE}/api/experiments/${filename}/metrics${params}`).then(r => r.json());
  },
};

export class LiveWebSocket {
  constructor(onMessage, onStatus) {
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.ws = null;
    this.reconnectTimer = null;
    this.connect();
  }

  connect() {
    try {
      this.ws = new WebSocket(`${WS_BASE}/ws`);
      
      this.ws.onopen = () => {
        console.log('WebSocket connected');
        this.onStatus?.('connected');
      };
      
      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.onMessage?.(data);
        } catch (e) {
          console.error('WebSocket parse error:', e);
        }
      };
      
      this.ws.onclose = () => {
        console.log('WebSocket disconnected');
        this.onStatus?.('disconnected');
        this.scheduleReconnect();
      };
      
      this.ws.onerror = () => {
        this.onStatus?.('error');
      };
    } catch (e) {
      this.onStatus?.('error');
      this.scheduleReconnect();
    }
  }

  scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 3000);
  }

  close() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

export default API;
