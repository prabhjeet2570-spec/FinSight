import { API_BASE_URL } from '../config';
import type { QueryJobAccepted, QueryJobStatus, QueryRequest, QueryResponse } from '../types';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export type QueryResult =
  | { type: 'sync'; response: QueryResponse }
  | { type: 'async'; jobId: string; progress: string | null };

export const api = {
  async submitQuery(req: QueryRequest): Promise<QueryResult> {
    const res = await fetch(`${API_BASE_URL}/api/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });

    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch {
        // ignore
      }
      throw new ApiError(res.status, detail);
    }

    const body = await res.json();

    if (res.status === 202) {
      const job = body as QueryJobAccepted;
      return { type: 'async', jobId: job.job_id, progress: job.progress };
    }

    return { type: 'sync', response: body as QueryResponse };
  },

  pollJob(jobId: string): Promise<QueryJobStatus> {
    return request<QueryJobStatus>(`/api/query/jobs/${jobId}`);
  },

  health(): Promise<{ status: string; service: string }> {
    return request<{ status: string; service: string }>('/health');
  },
};
