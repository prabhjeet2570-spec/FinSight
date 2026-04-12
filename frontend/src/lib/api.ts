import { API_BASE_URL } from '../config';
import type {
  DocumentResponse,
  DocumentStatusResponse,
  QueryRequest,
  QueryResponse,
  UploadResponse,
} from '../types';

class ApiError extends Error {
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
      // ignore — keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  uploadDocuments(files: File[]): Promise<UploadResponse> {
    const form = new FormData();
    for (const f of files) form.append('files', f);
    return request<UploadResponse>('/api/documents/upload', {
      method: 'POST',
      body: form,
    });
  },

  listDocuments(): Promise<DocumentResponse[]> {
    return request<DocumentResponse[]>('/api/documents');
  },

  getDocumentStatus(id: string): Promise<DocumentStatusResponse> {
    return request<DocumentStatusResponse>(`/api/documents/${id}/status`);
  },

  deleteDocument(id: string): Promise<{ detail: string }> {
    return request<{ detail: string }>(`/api/documents/${id}`, {
      method: 'DELETE',
    });
  },

  query(req: QueryRequest): Promise<QueryResponse> {
    return request<QueryResponse>('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
  },

  health(): Promise<{ status: string; service: string }> {
    return request<{ status: string; service: string }>('/health');
  },
};

export { ApiError };
