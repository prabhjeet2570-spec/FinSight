import { useCallback, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { DocumentResponse } from '../types';

const MAX_FILES = 4;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_TOTAL_BYTES = 40 * 1024 * 1024;

interface Props {
  existingCount: number;
  onUploaded: (docs: DocumentResponse[]) => void;
}

export function UploadZone({ existingCount, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validateAndUpload = useCallback(
    async (files: File[]) => {
      setError(null);

      const pdfs = files.filter((f) => f.name.toLowerCase().endsWith('.pdf'));
      if (pdfs.length === 0) {
        setError('Only PDF files are accepted.');
        return;
      }
      if (existingCount + pdfs.length > MAX_FILES) {
        setError(`Maximum ${MAX_FILES} documents total. You have ${existingCount}.`);
        return;
      }
      let total = 0;
      for (const f of pdfs) {
        if (f.size > MAX_FILE_BYTES) {
          setError(`${f.name} exceeds 10MB limit.`);
          return;
        }
        total += f.size;
      }
      if (total > MAX_TOTAL_BYTES) {
        setError('Combined upload exceeds 40MB.');
        return;
      }

      setUploading(true);
      try {
        const res = await api.uploadDocuments(pdfs);
        onUploaded(res.documents);
      } catch (e) {
        if (e instanceof ApiError) {
          setError(e.message);
        } else {
          setError('Upload failed. Is the backend running?');
        }
      } finally {
        setUploading(false);
      }
    },
    [existingCount, onUploaded],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = Array.from(e.dataTransfer.files);
      void validateAndUpload(files);
    },
    [validateAndUpload],
  );

  const onPick = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      void validateAndUpload(files);
      // reset so the same file can be re-picked
      if (inputRef.current) inputRef.current.value = '';
    },
    [validateAndUpload],
  );

  const disabled = uploading || existingCount >= MAX_FILES;

  return (
    <div className="upload-zone-wrapper">
      <div
        className={`upload-zone${dragging ? ' dragging' : ''}${disabled ? ' disabled' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        role="button"
        tabIndex={0}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={onPick}
        />
        {uploading ? (
          <p className="upload-text">Uploading…</p>
        ) : existingCount >= MAX_FILES ? (
          <p className="upload-text">Document limit reached ({MAX_FILES} max)</p>
        ) : (
          <>
            <p className="upload-text">Drop SEC filings here or click to browse</p>
            <p className="upload-sub">PDF · up to {MAX_FILES} files · 10MB each</p>
          </>
        )}
      </div>
      {error && <p className="upload-error">{error}</p>}
    </div>
  );
}
