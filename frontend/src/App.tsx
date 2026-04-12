import { useCallback, useEffect, useRef, useState } from 'react';
import './App.css';
import { ChatPanel } from './components/ChatPanel';
import { DocumentList } from './components/DocumentList';
import { UploadZone } from './components/UploadZone';
import { api } from './lib/api';
import type { DocumentResponse } from './types';

type BackendState = 'waking' | 'ready' | 'error';

function App() {
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [backend, setBackend] = useState<BackendState>('waking');
  const retryRef = useRef(0);

  useEffect(() => {
    let cancelled = false;

    const boot = async () => {
      while (!cancelled) {
        try {
          await api.health();
          if (cancelled) return;
          // Backend is up — load documents
          const docs = await api.listDocuments();
          if (!cancelled) {
            setDocuments(docs);
            setBackend('ready');
          }
          return;
        } catch {
          retryRef.current += 1;
          if (retryRef.current > 20) {
            if (!cancelled) setBackend('error');
            return;
          }
          // Exponential backoff: 1s, 2s, 3s... capped at 5s
          const delay = Math.min(retryRef.current * 1000, 5000);
          await new Promise((r) => setTimeout(r, delay));
        }
      }
    };

    void boot();
    return () => { cancelled = true; };
  }, []);

  const handleUploaded = useCallback((newDocs: DocumentResponse[]) => {
    setDocuments((prev) => [...newDocs, ...prev]);
  }, []);

  const handleStatusUpdate = useCallback(
    (id: string, patch: Partial<DocumentResponse>) => {
      setDocuments((prev) =>
        prev.map((d) => (d.id === id ? { ...d, ...patch } : d)),
      );
    },
    [],
  );

  const handleToggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }, []);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await api.deleteDocument(id);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
      setSelectedIds((prev) => prev.filter((x) => x !== id));
    } catch {
      // surface in UI later if needed
    }
  }, []);

  return (
    <div className="app">
      <header className="header">
        <h1 className="logo">
          <span className="logo-fin">Fin</span>
          <span className="logo-sight">Sight</span>
        </h1>
        <p className="tagline">Grounded financial intelligence for SEC filings</p>
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

      <main className="main-grid">
        <aside className="docs-pane">
          <section className="pane-section">
            <h2>Documents</h2>
            <UploadZone existingCount={documents.length} onUploaded={handleUploaded} />
          </section>

          <section className="pane-section docs-list-section">
            <DocumentList
              documents={documents}
              selectedIds={selectedIds}
              onToggleSelect={handleToggleSelect}
              onDelete={handleDelete}
              onStatusUpdate={handleStatusUpdate}
            />
          </section>
        </aside>

        <section className="chat-pane">
          <ChatPanel documents={documents} selectedIds={selectedIds} />
        </section>
      </main>
    </div>
  );
}

export default App;
