export function JobProgress({ progress }: { progress?: string | null }) {
  return (
    <div className="job-progress">
      <div className="job-spinner" />
      <span>{progress || 'Processing\u2026'}</span>
    </div>
  );
}
