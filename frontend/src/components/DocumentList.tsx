import { useEffect } from 'react';
import { api } from '../lib/api';
import type { DocumentResponse } from '../types';

interface Props {
  documents: DocumentResponse[];
  selectedIds: string[];
  onToggleSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onStatusUpdate: (id: string, patch: Partial<DocumentResponse>) => void;
}

const POLL_INTERVAL_MS = 2500;

export function DocumentList({
  documents,
  selectedIds,
  onToggleSelect,
  onDelete,
  onStatusUpdate,
}: Props) {
  // Poll status for any document still processing
  useEffect(() => {
    const processing = documents.filter((d) => d.status === 'processing');
    if (processing.length === 0) return;

    let cancelled = false;
    const tick = async () => {
      for (const doc of processing) {
        try {
          const status = await api.getDocumentStatus(doc.id);
          if (cancelled) return;
          if (status.status !== doc.status || status.company !== doc.company) {
            onStatusUpdate(doc.id, {
              status: status.status,
              company: status.company,
              page_count: status.page_count,
            });
          }
        } catch {
          // ignore transient failures — next tick will retry
        }
      }
    };
    const handle = window.setInterval(tick, POLL_INTERVAL_MS);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [documents, onStatusUpdate]);

  if (documents.length === 0) {
    return <p className="docs-empty">No documents yet. Upload a 10-Q or 10-K to begin.</p>;
  }

  return (
    <ul className="doc-list">
      {documents.map((doc) => {
        const selected = selectedIds.includes(doc.id);
        const isReady = doc.status === 'ready';
        return (
          <li key={doc.id} className={`doc-item${selected ? ' selected' : ''}`}>
            <label className="doc-row">
              <input
                type="checkbox"
                checked={selected}
                disabled={!isReady}
                onChange={() => onToggleSelect(doc.id)}
              />
              <div className="doc-meta">
                <div className="doc-title">{doc.filename ?? 'Untitled'}</div>
                <div className="doc-sub">
                  {doc.company !== 'Unknown' && <span>{doc.company}</span>}
                  {doc.filing_type && <span> · {doc.filing_type}</span>}
                  {doc.period && <span> · {doc.period}</span>}
                  {doc.page_count != null && <span> · {doc.page_count}p</span>}
                </div>
              </div>
              <StatusBadge status={doc.status} />
              <button
                className="doc-delete"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onDelete(doc.id);
                }}
                aria-label="Delete document"
                title="Delete document"
              >
                ×
              </button>
            </label>
          </li>
        );
      })}
    </ul>
  );
}

function StatusBadge({ status }: { status: DocumentResponse['status'] }) {
  const label =
    status === 'ready' ? 'ready' : status === 'failed' ? 'failed' : 'processing';
  return <span className={`status-badge status-${status}`}>{label}</span>;
}
