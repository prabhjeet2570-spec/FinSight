export function JobProgress({ progress }: { progress?: string | null }) {
  return (
    <div className="job-progress">
      <div className="job-progress-row">
        <span className="job-spinner">▮</span>
        <span className="job-progress-text">{progress || 'Processing…'}</span>
      </div>
      <div className="job-bar" />
    </div>
  );
}
