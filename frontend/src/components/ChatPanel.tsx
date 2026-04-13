import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { ChatMessage } from '../types';
import { AnswerBubble, AnswerCard } from './AnswerBubble';

interface Example {
  category: 'METRICS' | 'RISK' | 'COMPARE' | 'EVENTS' | 'EXECUTIVE' | 'DEEP';
  question: string;
}

const EXAMPLES: Example[] = [
  { category: 'METRICS',   question: "How is Apple's revenue trending?" },
  { category: 'RISK',      question: "What are NVIDIA's biggest risk factors?" },
  { category: 'COMPARE',   question: "Compare Microsoft and Google's operating margins" },
  { category: 'EVENTS',    question: "Any recent news or events about Tesla?" },
  { category: 'EXECUTIVE', question: "How much does Tim Cook get paid?" },
];

const CATEGORY_CLASS: Record<Example['category'], string> = {
  METRICS:   'tag-metrics',
  RISK:      'tag-risk',
  COMPARE:   'tag-compare',
  EVENTS:    'tag-strategy',
  EXECUTIVE: 'tag-outlook',
  DEEP:      'tag-deep',
};

const POLL_INTERVAL_MS = 2500;
const STORAGE_KEY = 'finsight-chat';

function loadMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatMessage[];
    return parsed.filter((m) => !m.pending);
  } catch {
    return [];
  }
}

function saveMessages(messages: ChatMessage[]) {
  try {
    const toSave = messages.filter((m) => !m.pending);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
  } catch {
    /* storage full or unavailable */
  }
}

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    saveMessages(messages);
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  // auto-resize the textarea
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }, [input]);

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

  const clearSession = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages([]);
    setInput('');
    setBusy(false);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    inputRef.current?.focus();
  }, []);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void submit(input);
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l') {
      e.preventDefault();
      clearSession();
    }
  };

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const hasMessages = messages.length > 0;

  return (
    <div className="chat-panel">
      <div className="chat-scroll" ref={scrollRef}>
        {!hasMessages ? (
          <Landing onSelect={(q) => void submit(q)} />
        ) : (
          <>
            <div className="chat-toolbar">
              <button className="new-chat-btn" onClick={clearSession} title="Clear chat (⌘L)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
                Clear chat
              </button>
            </div>
            {messages.map((m) => <MessageRow key={m.id} message={m} />)}
          </>
        )}
      </div>

      <div className="prompt-area">
        <div className="prompt-wrap">
          <textarea
            ref={inputRef}
            className="prompt-input"
            placeholder="Ask about any US public company…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            disabled={busy}
            autoFocus
          />
          <button
            className="prompt-send"
            onClick={() => void submit(input)}
            disabled={busy || !input.trim()}
            aria-label="Ask"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M13 5l7 7-7 7" />
            </svg>
          </button>
        </div>
        <div className="prompt-hint">
          <span><kbd>Enter</kbd> to send</span>
          <span><kbd>Shift</kbd> + <kbd>Enter</kbd> for newline</span>
        </div>
      </div>
    </div>
  );
}

function Landing({ onSelect }: { onSelect: (q: string) => void }) {
  return (
    <div className="landing">
      <div className="landing-badge">Grounded in SEC EDGAR filings</div>
      <h1 className="landing-title">
        Ask anything about <span className="gradient-text">SEC filings</span>
      </h1>
      <p className="landing-sub">
        Natural-language Q&amp;A over any US public company's 10-K, 10-Q, 8-K, and more.
      </p>
      <div className="examples-heading">Try one of these</div>
      <div className="examples-grid">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.question}
            className="example-card"
            onClick={() => onSelect(ex.question)}
          >
            <span className={`example-tag ${CATEGORY_CLASS[ex.category]}`}>{ex.category}</span>
            <span className="example-text">{ex.question}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageRow({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="msg-wrap msg-user">
        <div className="msg-user-bubble">{message.content}</div>
      </div>
    );
  }

  if (message.pending) {
    const progressText = message.progress;
    const statusLabel = progressText
      ? progressText.toLowerCase().includes('generat')
        ? 'Generating answer…'
        : progressText.toLowerCase().includes('search')
        ? 'Searching filings…'
        : progressText.toLowerCase().includes('sentiment') || progressText.toLowerCase().includes('finbert')
        ? 'Scoring sentiment…'
        : progressText.toLowerCase().includes('fetch') || progressText.toLowerCase().includes('edgar')
        ? 'Fetching records…'
        : progressText.toLowerCase().includes('resolv')
        ? 'Resolving filings…'
        : progressText
      : message.jobId
      ? 'Connecting to SEC EDGAR…'
      : 'Thinking…';

    return (
      <div className="msg-wrap">
        <AnswerCard>
          <div className="panel-pending">
            <div className="loader-orb" />
            <div className="pending-text">
              <div className="pending-title">{statusLabel}</div>
              {progressText && progressText !== statusLabel && (
                <div className="pending-detail">{progressText}</div>
              )}
            </div>
          </div>
          <div className="job-bar" />
        </AnswerCard>
      </div>
    );
  }

  if (message.error) {
    return (
      <div className="msg-wrap">
        <AnswerCard>
          <div className="panel-error">{message.error}</div>
        </AnswerCard>
      </div>
    );
  }

  return (
    <div className="msg-wrap">
      {message.response ? (
        <AnswerBubble response={message.response} />
      ) : (
        <AnswerCard>
          <div className="answer-body">
            <div className="answer-text">{message.content}</div>
          </div>
        </AnswerCard>
      )}
    </div>
  );
}
