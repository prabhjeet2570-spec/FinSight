import { useEffect, useRef, useState } from 'react';
import './App.css';
import { ChatPanel } from './components/ChatPanel';
import { api } from './lib/api';

type BackendState = 'waking' | 'ready' | 'error';

function App() {
  const [backend, setBackend] = useState<BackendState>('waking');
  const retryRef = useRef(0);

  useEffect(() => {
    let cancelled = false;

    const boot = async () => {
      while (!cancelled) {
        try {
          await api.health();
          if (!cancelled) setBackend('ready');
          return;
        } catch {
          retryRef.current += 1;
          if (retryRef.current > 20) {
            if (!cancelled) setBackend('error');
            return;
          }
          const delay = Math.min(retryRef.current * 1000, 5000);
          await new Promise((r) => setTimeout(r, delay));
        }
      }
    };

    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="app">
      <header className="header">
        <h1 className="logo">
          <span className="logo-fin">Fin</span>
          <span className="logo-sight">Sight</span>
        </h1>
        <p className="tagline">Explore SEC filings for any US public company</p>
      </header>

      {backend === 'waking' && (
        <div className="wake-banner">
          Waking up the server — free tier spins down after 15 min of inactivity...
        </div>
      )}

      {backend === 'error' && (
        <div className="wake-banner wake-error">
          Could not reach the FinSight backend. Make sure it is running on port 8000.
        </div>
      )}

      <main className="main-content">
        <ChatPanel />
      </main>
    </div>
  );
}

export default App;
