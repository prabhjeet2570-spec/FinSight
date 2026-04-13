export type CitationSource = 'text_chunk' | 'metric' | 'ratio';

export interface Citation {
  source_type: CitationSource;
  filing_id: string | null;
  page_num: number | null;
  section: string | null;
  metric_name: string | null;
  detail: string | null;
}

export type QueryType = 'NUMERICAL' | 'NARRATIVE' | 'MIXED' | 'SENTIMENT';
export type Confidence = 'high' | 'medium' | 'low';

export interface QueryRequest {
  question: string;
}

export interface CompanyResolved {
  ticker: string;
  name: string;
  cik: string;
}

export interface FilingUsed {
  filing_id: string;
  ticker: string;
  filing_type: string;
  period_label: string | null;
  accession_number: string;
  primary_doc_url: string | null;
}

export interface MetricUsed {
  name: string;
  value: number;
  prior_value: number | null;
  change_pct: number | null;
  unit: string | null;
  period: string | null;
  ticker: string | null;
}

export interface RatioComputed {
  name: string;
  display_name: string;
  value: number;
  prior_value: number | null;
  change_pct: number | null;
  format: string;
  ticker: string | null;
  period: string | null;
}

export interface SentimentResult {
  overall: 'positive' | 'negative' | 'neutral';
  positive_score: number;
  negative_score: number;
  neutral_score: number;
  analyzed_chunks: number;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  query_type: QueryType;
  confidence: Confidence;
  companies_resolved: CompanyResolved[];
  filings_used: FilingUsed[];
  metrics_used: MetricUsed[] | null;
  ratios_computed: RatioComputed[] | null;
  sentiment: SentimentResult | null;
}

export interface QueryJobAccepted {
  job_id: string;
  status: string;
  progress: string | null;
}

export interface QueryJobStatus {
  job_id: string;
  status: 'pending' | 'processing' | 'ready' | 'failed';
  progress: string | null;
  result: QueryResponse | null;
  error: string | null;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  response?: QueryResponse;
  error?: string;
  pending?: boolean;
  jobId?: string;
  progress?: string | null;
}
