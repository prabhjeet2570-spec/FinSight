import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { ChatMessage, Citation, DocumentResponse, QueryResponse, SentimentResult } from '../types';

interface Props {
  documents: DocumentResponse[];
  selectedIds: string[];
}

export function ChatPanel({ documents, selectedIds }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const readyCount = documents.filter((d) => d.status === 'ready').length;
  const targetIds = selectedIds.length > 0 ? selectedIds : undefined;
  const targetLabel =
    selectedIds.length > 0
      ? `${selectedIds.length} selected document${selectedIds.length === 1 ? '' : 's'}`
      : readyCount > 0
        ? `all ${readyCount} ready document${readyCount === 1 ? '' : 's'}`
        : 'no documents yet';

  const submit = async () => {
    const question = input.trim();
    if (!question || busy) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: question,
    };
    const placeholder: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      pending: true,
    };
    setMessages((m) => [...m, userMsg, placeholder]);
    setInput('');
    setBusy(true);

    try {
      const res = await api.query({ question, document_ids: targetIds });
      setMessages((m) =>
        m.map((msg) =>
          msg.id === placeholder.id
            ? { ...msg, pending: false, content: res.answer, response: res }
            : msg,
        ),
      );
    } catch (e) {
      const errMsg =
        e instanceof ApiError
          ? `${e.status === 404 ? 'Document not found.' : e.status === 409 ? 'Documents still processing — give it a moment.' : e.message}`
          : 'Something went wrong. Is the backend running?';
      setMessages((m) =>
        m.map((msg) =>
          msg.id === placeholder.id
            ? { ...msg, pending: false, content: '', error: errMsg }
            : msg,
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <h2>Ask a question</h2>
        <p className="chat-target">Querying {targetLabel}</p>
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 ? (
          <EmptyState ready={readyCount > 0} />
        ) : (
          messages.map((m) => <MessageBubble key={m.id} message={m} />)
        )}
      </div>

      <div className="chat-input-row">
        <textarea
          className="chat-input"
          placeholder={
            readyCount === 0
              ? 'Upload a filing first…'
              : 'Ask about revenue, margins, risk factors, MD&A…'
          }
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          disabled={readyCount === 0}
        />
        <button
          className="chat-send"
          onClick={() => void submit()}
          disabled={busy || readyCount === 0 || !input.trim()}
        >
          {busy ? '…' : 'Ask'}
        </button>
      </div>
    </div>
  );
}

function EmptyState({ ready }: { ready: boolean }) {
  return (
    <div className="chat-empty">
      {ready ? (
        <>
          <p className="chat-empty-title">Try asking:</p>
          <ul>
            <li>"What was revenue this quarter?"</li>
            <li>"How's the top line trending?"</li>
            <li>"What are the biggest risk factors?"</li>
            <li>"What's the gross margin?"</li>
            <li>"Summarize MD&amp;A on AI investment."</li>
          </ul>
        </>
      ) : (
        <p>Upload a 10-Q or 10-K to start asking questions.</p>
      )}
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="msg-bubble">{message.content}</div>
      </div>
    );
  }

  if (message.pending) {
    return (
      <div className="msg msg-assistant">
        <div className="msg-bubble msg-pending">Thinking…</div>
      </div>
    );
  }

  if (message.error) {
    return (
      <div className="msg msg-assistant">
        <div className="msg-bubble msg-error">{message.error}</div>
      </div>
    );
  }

  return (
    <div className="msg msg-assistant">
      <div className="msg-bubble">
        {message.response && <ResponseMeta response={message.response} />}
        <div className="msg-text">{message.content}</div>
        {message.response && message.response.citations.length > 0 && (
          <CitationList citations={message.response.citations} />
        )}
      </div>
    </div>
  );
}

function ResponseMeta({ response }: { response: QueryResponse }) {
  return (
    <div className="msg-meta">
      <span className={`tag tag-${response.confidence}`}>{response.confidence} confidence</span>
      <span className="tag tag-type">{response.query_type}</span>
      {response.sentiment && (
        <SentimentTag sentiment={response.sentiment} />
      )}
    </div>
  );
}

function SentimentTag({ sentiment }: { sentiment: SentimentResult }) {
  const cls =
    sentiment.overall === 'positive'
      ? 'tag-high'
      : sentiment.overall === 'negative'
        ? 'tag-low'
        : 'tag-type';
  const pct = Math.round(
    (sentiment.overall === 'positive'
      ? sentiment.positive_score
      : sentiment.overall === 'negative'
        ? sentiment.negative_score
        : sentiment.neutral_score) * 100,
  );
  return (
    <span className={`tag ${cls}`} title={`${sentiment.analyzed_chunks} passages analyzed`}>
      {sentiment.overall} {pct}%
    </span>
  );
}

function CitationList({ citations }: { citations: Citation[] }) {
  return (
    <details className="citations">
      <summary>{citations.length} source{citations.length === 1 ? '' : 's'}</summary>
      <ul>
        {citations.map((c, i) => (
          <li key={i}>
            <span className={`cite-type cite-${c.source_type}`}>{c.source_type}</span>
            {c.metric_name && <span className="cite-metric"> {c.metric_name}</span>}
            {c.page_num != null && <span className="cite-page"> · page {c.page_num}</span>}
            {c.section && <span className="cite-section"> · {c.section}</span>}
            {c.detail && <div className="cite-detail">{c.detail}</div>}
          </li>
        ))}
      </ul>
    </details>
  );
}
