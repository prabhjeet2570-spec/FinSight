"""In-memory job queue for long-running query requests.

When a /api/query call needs to fetch + ingest one or more filings from
EDGAR, the work takes 60-180s — too long to hold an HTTP connection on
Render's free tier. Instead the router creates a job, kicks off the
background work, and returns the job_id. The frontend polls
/api/query/jobs/{id} every couple of seconds.

This is intentionally simple: a process-local dict guarded by an
asyncio.Lock. It works because Render free tier runs a single process
per service. If we ever need multi-worker we'd swap this for Redis or
Postgres-backed jobs — the public functions stay the same.

The dict is bounded by an LRU cap so a long-running server doesn't
accumulate indefinitely. Completed jobs are kept around for 30 minutes
so the frontend has time to poll the result, then evicted.
"""
import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"        # created, work not started yet
    PROCESSING = "processing"  # background task is running
    READY = "ready"            # finished, result is populated
    FAILED = "failed"          # finished with an error


@dataclass
class JobState:
    id: str
    status: JobStatus
    progress: str | None = None  # human-readable status (e.g. "Fetching from EDGAR…")
    result: Any | None = None    # populated when status == READY
    error: str | None = None     # populated when status == FAILED
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


_MAX_JOBS = 1000           # hard cap to bound memory
_FINISHED_TTL_MIN = 30     # finished jobs stay around for ~30min then get evicted
_jobs: "OrderedDict[str, JobState]" = OrderedDict()
_lock = asyncio.Lock()


def _evict_expired_locked() -> None:
    """Drop finished jobs older than the TTL. Caller must hold _lock."""
    cutoff = datetime.utcnow() - timedelta(minutes=_FINISHED_TTL_MIN)
    expired = [
        jid for jid, j in _jobs.items()
        if j.status in (JobStatus.READY, JobStatus.FAILED) and j.updated_at < cutoff
    ]
    for jid in expired:
        del _jobs[jid]
    # Hard cap (oldest-first eviction) regardless of TTL
    while len(_jobs) > _MAX_JOBS:
        _jobs.popitem(last=False)


async def create_job() -> str:
    """Create a new job in PENDING status and return its id."""
    async with _lock:
        _evict_expired_locked()
        job_id = uuid4().hex
        _jobs[job_id] = JobState(id=job_id, status=JobStatus.PENDING)
        return job_id


async def get_job(job_id: str) -> JobState | None:
    async with _lock:
        return _jobs.get(job_id)


async def set_progress(job_id: str, message: str) -> None:
    """Mark a job as PROCESSING (if not already finished) and update its progress message."""
    async with _lock:
        job = _jobs.get(job_id)
        if job is None:
            logger.warning(f"set_progress: unknown job_id {job_id}")
            return
        if job.status not in (JobStatus.READY, JobStatus.FAILED):
            job.status = JobStatus.PROCESSING
        job.progress = message
        job.updated_at = datetime.utcnow()
        logger.info(f"job {job_id[:8]}: {message}")


async def set_result(job_id: str, result: Any) -> None:
    async with _lock:
        job = _jobs.get(job_id)
        if job is None:
            logger.warning(f"set_result: unknown job_id {job_id}")
            return
        job.status = JobStatus.READY
        job.result = result
        job.progress = None
        job.updated_at = datetime.utcnow()


async def set_error(job_id: str, error: str) -> None:
    async with _lock:
        job = _jobs.get(job_id)
        if job is None:
            logger.warning(f"set_error: unknown job_id {job_id}")
            return
        job.status = JobStatus.FAILED
        job.error = error[:1000]
        job.progress = None
        job.updated_at = datetime.utcnow()
