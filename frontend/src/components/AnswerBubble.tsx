import type { FilingUsed, QueryResponse, SentimentResult } from '../types';

export function AnswerBubble({ response }: { response: QueryResponse }) {
  return (
    <div className="answer-bubble">
      {response.sentiment && (
        <div className="answer-tags">
          <SentimentTag sentiment={response.sentiment} />
        </div>
      )}

      <div className="answer-text">{response.answer}</div>

      {response.filings_used.length > 0 && (
        <SourcesList filings={response.filings_used} />
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
        : 'tag-neutral';
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

function SourcesList({ filings }: { filings: FilingUsed[] }) {
  return (
    <details className="citations">
      <summary>
        {filings.length} filing{filings.length === 1 ? '' : 's'} used
      </summary>
      <ul>
        {filings.map((f) => {
          const label = [f.ticker, f.filing_type, f.period_label]
            .filter(Boolean)
            .join(' \u00b7 ');
          return (
            <li key={f.filing_id}>
              {f.primary_doc_url ? (
                <a
                  className="source-filing"
                  href={f.primary_doc_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {label}
                </a>
              ) : (
                <span className="source-filing">{label}</span>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
