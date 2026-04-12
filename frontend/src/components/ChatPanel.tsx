import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { ChatMessage } from '../types';
import { AnswerBubble } from './AnswerBubble';
import { JobProgress } from './JobProgress';

const SUGGESTIONS = [
  "How is Apple's revenue trending?",
  "What are NVIDIA's biggest risk factors?",
  "Compare Microsoft and Google's operating margins",
  "Is Tesla's management optimistic about next year?",
  "What did Meta say about AI in their last 10-Q?",
];

const POLL_INTERVAL_MS = 2500;

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const updateMessage = useCallback((id: string, updates: Partial<ChatMessage>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...updates } : m)));
  }, []);

  const submit = useCallback(
    async (question: string) => {
      question = question.trim();
      if (!question || busy) return;

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content: question,
      };
      const assistantId = crypto.randomUUID();
      const placeholder: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        pending: true,
      };
      setMessages((prev) => [...prev, userMsg, placeholder]);
      setInput('');
      setBusy(true);

      try {
        const result = await api.submitQuery({ question });

        if (result.type === 'sync') {
          updateMessage(assistantId, {
            pending: false,
            content: result.response.answer,
            response: result.response,
          });
        } else {
          updateMessage(assistantId, {
            pending: true,
            jobId: result.jobId,
            progress: result.progress,
          });

          const abort = new AbortController();
          abortRef.current = abort;

          while (!abort.signal.aborted) {
            await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
            if (abort.signal.aborted) break;

            const job = await api.pollJob(result.jobId);

            if (job.status === 'ready' && job.result) {
              updateMessage(assistantId, {
                pending: false,
                content: job.result.answer,
                response: job.result,
                progress: undefined,
                jobId: undefined,
              });
              break;
            }

            if (job.status === 'failed') {
              updateMessage(assistantId, {
                pending: false,
                error: job.error || 'Query failed',
                progress: undefined,
                jobId: undefined,
              });
              break;
            }

            updateMessage(assistantId, { progress: job.progress });
          }

          abortRef.current = null;
        }
      } catch (e) {
        const errMsg =
          e instanceof ApiError ? e.message : 'Something went wrong. Is the backend running?';
        updateMessage(assistantId, { pending: false, error: errMsg });
      } finally {
        setBusy(false);
      }
    },
    [busy, updateMessage],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void submit(input);
    }
  };

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return (
    <div className="chat-panel">
      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 ? (
          <EmptyState onSelect={(q) => void submit(q)} />
        ) : (
          messages.map((m) => <MessageRow key={m.id} message={m} />)
        )}
      </div>

      <div className="chat-input-area">
        <div className="chat-input-row">
          <textarea
            className="chat-input"
            placeholder="Ask about any company's SEC filings\u2026"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            disabled={busy}
          />
          <button
            className="chat-send"
            onClick={() => void submit(input)}
            disabled={busy || !input.trim()}
          >
            {busy ? '\u2026' : 'Ask'}
          </button>
        </div>
      </div>
    </div>
  );
}

function EmptyState({ onSelect }: { onSelect: (q: string) => void }) {
  return (
    <div className="chat-empty">
      <p className="chat-empty-title">Try asking:</p>
      <div className="suggestion-chips">
        {SUGGESTIONS.map((q) => (
          <button key={q} className="suggestion-chip" onClick={() => onSelect(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageRow({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="msg-bubble">{message.content}</div>
      </div>
    );
  }

  if (message.pending && message.jobId) {
    return (
      <div className="msg msg-assistant">
        <div className="msg-bubble">
          <JobProgress progress={message.progress} />
        </div>
      </div>
    );
  }

  if (message.pending) {
    return (
      <div className="msg msg-assistant">
        <div className="msg-bubble msg-pending">Thinking&hellip;</div>
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
        {message.response ? (
          <AnswerBubble response={message.response} />
        ) : (
          <div className="answer-text">{message.content}</div>
        )}
      </div>
    </div>
  );
}
