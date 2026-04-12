// Mirrors backend Pydantic models in app/models/document.py and app/models/query.py

export type DocumentStatus = 'processing' | 'ready' | 'failed';

export interface DocumentResponse {
  id: string;
  filename: string | null;
  company: string;
  filing_type: string | null;
  period: string | null;
  uploaded_at: string;
  page_count: number | null;
  status: DocumentStatus;
}

export interface UploadResponse {
  documents: DocumentResponse[];
  message: string;
}

export interface DocumentStatusResponse {
  id: string;
  status: DocumentStatus;
  filename: string | null;
  company: string;
  page_count: number | null;
}

export interface MetricResponse {
  id: string;
  metric_name: string;
  value: number | null;
  prior_value: number | null;
  change_pct: number | null;
  unit: string | null;
  period: string | null;
  prior_period: string | null;
  page_num: number | null;
  table_type: string | null;
}

export type CitationSource = 'text_chunk' | 'metric' | 'ratio';

export interface Citation {
  source_type: CitationSource;
  document_id: string | null;
  page_num: number | null;
  section: string | null;
  metric_name: string | null;
  detail: string | null;
}

export type QueryType = 'NUMERICAL' | 'NARRATIVE' | 'MIXED' | 'SENTIMENT';
export type Confidence = 'high' | 'medium' | 'low';

export interface QueryRequest {
  question: string;
  document_ids?: string[];
}

export interface MetricUsed {
  name: string;
  value: number;
  prior_value: number | null;
  change_pct: number | null;
  unit: string | null;
  period: string | null;
}

export interface RatioComputed {
  name: string;
  display_name: string;
  value: number;
  prior_value: number | null;
  change_pct: number | null;
  format: string;
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
  metrics_used: MetricUsed[] | null;
  ratios_computed: RatioComputed[] | null;
  sentiment: SentimentResult | null;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  response?: QueryResponse;
  error?: string;
  pending?: boolean;
}
