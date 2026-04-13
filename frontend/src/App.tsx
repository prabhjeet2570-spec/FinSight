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

  const statusLabel =
    backend === 'ready' ? 'Ready' : backend === 'waking' ? 'Warming up' : 'Offline';

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path
                d="M4 18 L9 11 L13 14 L20 6"
                stroke="white"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <circle cx="20" cy="6" r="1.8" fill="white" />
            </svg>
          </div>
          <div className="brand-name">
            Fin<span className="accent">Sight</span>
          </div>
          <div className="brand-tagline">
            AI-powered insights from SEC filings of US public companies
          </div>
        </div>

        <div className={`header-status status-${backend}`}>
          <span className="status-dot" />
          <span>{statusLabel}</span>
        </div>
      </header>

      {backend === 'waking' && (
        <div className="banner banner-warn">
          Warming up the server — free tier spins down after 15 min idle…
        </div>
      )}

      {backend === 'error' && (
        <div className="banner banner-error">
          Cannot reach the FinSight backend. Make sure it is running on port 8000.
        </div>
      )}

      <main>
        <ChatPanel />
      </main>
    </div>
  );
}

export default App;
