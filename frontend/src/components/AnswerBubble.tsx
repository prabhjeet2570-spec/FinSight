import React from 'react';
import type { ReactNode } from 'react';
import type {
  FilingUsed,
  MetricUsed,
  QueryResponse,
  RatioComputed,
  SentimentResult,
} from '../types';

/* ---------- Display helpers ---------- */

const METRIC_LABELS: Record<string, string> = {
  revenue: 'Revenue',
  cost_of_revenue: 'Cost of Revenue',
  gross_profit: 'Gross Profit',
  operating_income: 'Operating Income',
  net_income: 'Net Income',
  eps_basic: 'EPS (Basic)',
  eps_diluted: 'EPS (Diluted)',
  ebitda: 'EBITDA',
  operating_expenses: 'Operating Expenses',
  research_and_development: 'R&D',
  selling_general_admin: 'SG&A',
  cash_and_equivalents: 'Cash & Equivalents',
  accounts_receivable: 'Accounts Receivable',
  inventories: 'Inventory',
  current_assets: 'Current Assets',
  total_assets: 'Total Assets',
  accounts_payable: 'Accounts Payable',
  current_liabilities: 'Current Liabilities',
  long_term_debt: 'Long-term Debt',
  total_debt: 'Total Debt',
  total_liabilities: 'Total Liabilities',
  stockholders_equity: 'Equity',
  operating_cash_flow: 'Operating Cash Flow',
  capital_expenditures: 'Capex',
  free_cash_flow: 'Free Cash Flow',
  depreciation_amortization: 'D&A',
  stock_based_compensation: 'SBC',
  dividends_per_share: 'DPS',
  dividends_paid: 'Dividends Paid',
  share_repurchases: 'Buybacks',
};

function labelFor(name: string): string {
  return (
    METRIC_LABELS[name] ||
    name
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);

  if (abs > 0 && abs < 1000) {
    return value.toFixed(2);
  }

  let scaled = value;
  let suffix = '';
  if (abs >= 1e12) {
    scaled = value / 1e12;
    suffix = 'T';
  } else if (abs >= 1e9) {
    scaled = value / 1e9;
    suffix = 'B';
  } else if (abs >= 1e6) {
    scaled = value / 1e6;
    suffix = 'M';
  } else if (abs >= 1e3) {
    scaled = value / 1e3;
    suffix = 'K';
  }

  const decimals = Math.abs(scaled) >= 100 ? 1 : 2;
  return `$${scaled.toFixed(decimals)}${suffix}`;
}

function formatPercent(p: number | null | undefined): string {
  if (p === null || p === undefined || Number.isNaN(p)) return '—';
  const sign = p > 0 ? '+' : '';
  return `${sign}${p.toFixed(2)}%`;
}

function deltaClass(change: number | null | undefined): 'pos' | 'neg' | 'neu' {
  if (change === null || change === undefined || Number.isNaN(change)) return 'neu';
  if (change > 0) return 'pos';
  if (change < 0) return 'neg';
  return 'neu';
}

function deltaArrow(change: number | null | undefined): string {
  if (change === null || change === undefined || Number.isNaN(change)) return '·';
  if (change > 0) return '▲';
  if (change < 0) return '▼';
  return '·';
}

/* ---------- Simple markdown renderer ---------- */

function renderMarkdown(text: string): ReactNode {
  const lines = text.split('\n');
  const elements: ReactNode[] = [];
  let currentList: ReactNode[] = [];

  const flushList = () => {
    if (currentList.length > 0) {
      elements.push(<ul key={`ul-${elements.length}`}>{currentList}</ul>);
      currentList = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const bulletMatch = line.match(/^\s*[\*\-]\s+(.+)/);

    if (bulletMatch) {
      currentList.push(<li key={i}>{renderInline(bulletMatch[1])}</li>);
    } else {
      flushList();
      const trimmed = line.trim();
      if (trimmed === '') {
        if (elements.length > 0) {
          elements.push(<br key={`br-${i}`} />);
        }
      } else {
        elements.push(<p key={i}>{renderInline(trimmed)}</p>);
      }
    }
  }
  flushList();

  return <>{elements}</>;
}

function renderInline(text: string): ReactNode {
  // Parse **bold** segments
  const parts: ReactNode[] = [];
  const regex = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(<strong key={match.index}>{match[1]}</strong>);
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length === 1 ? parts[0] : <>{parts}</>;
}

/* ---------- Unified data row ---------- */

interface UnifiedRow {
  key: string;
  label: string;
  value: number | null;
  prior_value: number | null;
  change_pct: number | null;
  displayValue: string;
  displayPrior: string;
  ticker: string | null;
  period: string | null;
}

function metricsToRows(metrics: MetricUsed[]): UnifiedRow[] {
  return metrics.map((m) => ({
    key: m.name,
    label: labelFor(m.name),
    value: m.value,
    prior_value: m.prior_value,
    change_pct: m.change_pct,
    displayValue: formatValue(m.value),
    displayPrior: m.prior_value !== null ? formatValue(m.prior_value) : '—',
    ticker: m.ticker,
    period: m.period,
  }));
}

function ratiosToRows(ratios: RatioComputed[]): UnifiedRow[] {
  return ratios.map((r) => {
    let displayValue = '—';
    if (r.value !== null && r.value !== undefined) {
      if (r.format === 'percentage') displayValue = `${r.value.toFixed(2)}%`;
      else if (r.format === 'ratio') displayValue = `${r.value.toFixed(2)}x`;
      else if (r.format === 'currency') displayValue = formatValue(r.value);
      else displayValue = r.value.toFixed(2);
    }
    let displayPrior = '—';
    if (r.prior_value !== null && r.prior_value !== undefined) {
      if (r.format === 'percentage') displayPrior = `${r.prior_value.toFixed(2)}%`;
      else if (r.format === 'ratio') displayPrior = `${r.prior_value.toFixed(2)}x`;
      else displayPrior = r.prior_value.toFixed(2);
    }
    return {
      key: r.name,
      label: r.display_name,
      value: r.value,
      prior_value: r.prior_value,
      change_pct: r.change_pct,
      displayValue,
      displayPrior,
      ticker: r.ticker,
      period: r.period,
    };
  });
}

/* ---------- Dedup ---------- */

/** Keep one row per (metric, ticker). Last occurrence wins (most recent filing). */
function dedup(rows: UnifiedRow[]): UnifiedRow[] {
  const map = new Map<string, UnifiedRow>();
  for (const r of rows) {
    map.set(`${r.key}::${r.ticker ?? ''}`, r);
  }
  return Array.from(map.values());
}

/* ---------- Shared card wrapper ---------- */

export function AnswerCard({ children }: { children: ReactNode }) {
  return <div className="answer-card">{children}</div>;
}

/* ---------- Main answer bubble ---------- */

export function AnswerBubble({ response }: { response: QueryResponse }) {
  const uniqueCompanies = response.companies_resolved.filter(
    (c, i, arr) => arr.findIndex((x) => x.ticker === c.ticker) === i,
  );
  const isMultiCompany = uniqueCompanies.length > 1;
  const company = uniqueCompanies[0];

  const ticker = company?.ticker || response.filings_used[0]?.ticker || null;
  const companyName = isMultiCompany
    ? uniqueCompanies.map((c) => c.name).join(' vs ')
    : company?.name || (ticker ? `${ticker}` : 'Analysis');

  // Merge metrics + ratios, deduplicated (last occurrence per metric wins)
  const showTable = response.query_type === 'NUMERICAL';
  const allRows = showTable
    ? dedup([
        ...(response.metrics_used ? metricsToRows(response.metrics_used) : []),
        ...(response.ratios_computed ? ratiosToRows(response.ratios_computed) : []),
      ])
    : [];

  const tickers = isMultiCompany
    ? uniqueCompanies.map((c) => c.ticker)
    : [];

  return (
    <AnswerCard>
      <div className="answer-head">
        {isMultiCompany ? (
          <div className="ticker-avatar-group">
            {uniqueCompanies.map((c) => (
              <TickerAvatar key={c.ticker} ticker={c.ticker} />
            ))}
          </div>
        ) : (
          <TickerAvatar ticker={ticker} />
        )}
        <div className="answer-title-wrap">
          <div className="answer-title">{companyName}</div>
        </div>
      </div>

      <div className="answer-body">
        {allRows.length > 0 && (
          <Section title="Financial data">
            {isMultiCompany ? (
              <ComparisonTable rows={allRows} tickers={tickers} />
            ) : (
              <SingleTable rows={allRows} />
            )}
          </Section>
        )}

        {response.sentiment && (
          <Section title="Sentiment">
            <SentimentBars sentiment={response.sentiment} />
          </Section>
        )}

        <Section title="Analysis">
          <div className="answer-text">{renderMarkdown(response.answer)}</div>
        </Section>

        {response.filings_used.length > 0 && (
          <Section
            title={`Sources · ${response.filings_used.length} filing${
              response.filings_used.length === 1 ? '' : 's'
            }`}
          >
            <SourcesList filings={response.filings_used} />
          </Section>
        )}
      </div>
    </AnswerCard>
  );
}

/* ---------- Ticker avatar ---------- */

function TickerAvatar({ ticker }: { ticker: string | null }) {
  if (!ticker) {
    return <div className="ticker-avatar ticker-avatar-generic">—</div>;
  }
  return <div className="ticker-avatar">{ticker}</div>;
}

/* ---------- Section wrapper ---------- */

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div className="section-title">{title}</div>
      {children}
    </div>
  );
}

/* ---------- Single-company unified table ---------- */

function SingleTable({ rows }: { rows: UnifiedRow[] }) {
  return (
    <div className="data-block">
      <table className="data-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th className="num">Period</th>
            <th className="num">Value</th>
            <th className="num">Δ YoY</th>
            <th className="num">Prior</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const cls = deltaClass(r.change_pct);
            const arrow = deltaArrow(r.change_pct);
            return (
              <tr key={`${r.key}-${i}`}>
                <td>{r.label}</td>
                <td className="num dim">{r.period || '—'}</td>
                <td className="num">{r.displayValue}</td>
                <td className="num">
                  <span className={`delta delta-${cls}`}>
                    {arrow} {formatPercent(r.change_pct)}
                  </span>
                </td>
                <td className="num dim">{r.displayPrior}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Side-by-side comparison table ---------- */

function ComparisonTable({
  rows,
  tickers,
}: {
  rows: UnifiedRow[];
  tickers: string[];
}) {
  const metricOrder: string[] = [];
  const metricLabels = new Map<string, string>();
  const dataMap = new Map<string, Map<string, UnifiedRow>>();

  for (const row of rows) {
    const t = row.ticker ?? '??';
    if (!dataMap.has(row.key)) {
      metricOrder.push(row.key);
      metricLabels.set(row.key, row.label);
      dataMap.set(row.key, new Map());
    }
    dataMap.get(row.key)!.set(t, row);
  }

  return (
    <div className="data-block">
      <table className="data-table comparison-table">
        <thead>
          <tr>
            <th>Metric</th>
            {tickers.map((t) => (
              <th key={t} className="num compare-col" colSpan={3}>
                <span className="compare-ticker">{t}</span>
              </th>
            ))}
          </tr>
          <tr className="sub-header">
            <th />
            {tickers.map((t) => (
              <React.Fragment key={t}>
                <th className="num sub">Period</th>
                <th className="num sub">Value</th>
                <th className="num sub">Δ YoY</th>
              </React.Fragment>
            ))}
          </tr>
        </thead>
        <tbody>
          {metricOrder.map((key) => {
            const tickerData = dataMap.get(key)!;
            return (
              <tr key={key}>
                <td>{metricLabels.get(key)}</td>
                {tickers.map((t) => {
                  const d = tickerData.get(t);
                  if (!d) {
                    return (
                      <React.Fragment key={t}>
                        <td className="num dim">—</td>
                        <td className="num dim">—</td>
                        <td className="num dim">—</td>
                      </React.Fragment>
                    );
                  }
                  const cls = deltaClass(d.change_pct);
                  const arrow = deltaArrow(d.change_pct);
                  return (
                    <React.Fragment key={t}>
                      <td className="num dim">{d.period || '—'}</td>
                      <td className="num">{d.displayValue}</td>
                      <td className="num">
                        <span className={`delta delta-${cls}`}>
                          {arrow} {formatPercent(d.change_pct)}
                        </span>
                      </td>
                    </React.Fragment>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Sentiment bars ---------- */

function SentimentBars({ sentiment }: { sentiment: SentimentResult }) {
  const rows: Array<{ label: string; val: number; cls: 'pos' | 'neu' | 'neg' }> = [
    { label: 'Positive', val: sentiment.positive_score, cls: 'pos' },
    { label: 'Neutral',  val: sentiment.neutral_score,  cls: 'neu' },
    { label: 'Negative', val: sentiment.negative_score, cls: 'neg' },
  ];

  const overallCls =
    sentiment.overall === 'positive'
      ? 'pos'
      : sentiment.overall === 'negative'
        ? 'neg'
        : 'neu';

  return (
    <div className="sentiment-wrap">
      <div className="sent-about">
        <div className="sent-source">
          FinBERT Sentiment Analysis
        </div>
        <div className="sent-explainer">
          FinBERT is an AI model trained on 10,000+ financial texts. It reads passages from the
          filing's MD&A section and scores each as positive (growth, confidence, improvement),
          negative (risk, decline, concern), or neutral (factual, no strong signal).
          The percentages below show how the language in the filing breaks down.
        </div>
      </div>
      {rows.map((r) => {
        const pct = Math.round(r.val * 100);
        return (
          <div key={r.label} className="sent-row">
            <span className="sent-label">{r.label}</span>
            <div className="sent-track">
              <div
                className={`sent-fill sent-fill-${r.cls}`}
                style={{ width: `${Math.max(pct, 2)}%` }}
              />
            </div>
            <span className="sent-pct">{pct}%</span>
          </div>
        );
      })}
      <div className="sent-overall">
        <span>Overall</span>
        <span className={`sent-badge sent-badge-${overallCls}`}>
          {sentiment.overall}
        </span>
        <span className="sent-overall-meta">
          {sentiment.analyzed_chunks} passages analyzed
        </span>
      </div>
    </div>
  );
}

/* ---------- Sources ---------- */

function SourcesList({ filings }: { filings: FilingUsed[] }) {
  return (
    <ol className="sources-list">
      {filings.map((f, i) => {
        const label = [f.ticker, f.filing_type, f.period_label]
          .filter(Boolean)
          .join(' · ');
        return (
          <li key={f.filing_id} className="source-item">
            <span className="source-num">F{String(i + 1).padStart(2, '0')}</span>
            {f.primary_doc_url ? (
              <a
                className="source-link"
                href={f.primary_doc_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <span>{label}</span>
                <svg
                  className="source-external"
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                  <path d="M15 3h6v6M10 14L21 3" />
                </svg>
              </a>
            ) : (
              <span className="source-link">{label}</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
