"""
File-based job state persistence.

Jobs are stored as JSON files in the jobs/ directory.
No external database required.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from rsi_supertrend_backtester.data_collection.config import settings
from rsi_supertrend_backtester.data_collection.models.job import Job, JobStatus, SymbolState, SymbolStatus
from rsi_supertrend_backtester.data_collection.utils.logger import get_logger

logger = get_logger(__name__)


class JobManager:
    """
    Manages job lifecycle with disk persistence.

    Jobs are read from and written to JSON files in settings.jobs_dir.
    An in-memory cache is kept for fast status reads during polling.
    """

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._jobs_dir = settings.jobs_dir

    def create_job(
        self,
        symbols: list[str],
        from_date: str,
        to_date: str,
        exchange_segment: str,
        instrument: str,
    ) -> Job:
        """Create a new job and persist it to disk."""
        job = Job(
            symbols=symbols,
            from_date=from_date,
            to_date=to_date,
            exchange_segment=exchange_segment,
            instrument=instrument,
            symbols_state={
                symbol: SymbolState(symbol=symbol) for symbol in symbols
            },
        )
        self._jobs[job.job_id] = job
        self._save(job)
        logger.info(f"Created job {job.job_id} for {len(symbols)} symbols")
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID, loading from disk if not in memory cache."""
        if job_id in self._jobs:
            return self._jobs[job_id]

        path = self._job_path(job_id)
        if path.exists():
            try:
                job = Job.model_validate_json(path.read_text())
                self._jobs[job_id] = job
                return job
            except Exception as e:
                logger.error(f"Failed to load job {job_id}: {e}")
                return None
        return None

    def update_symbol_status(
        self,
        job_id: str,
        symbol: str,
        status: SymbolStatus,
        **kwargs,
    ) -> None:
        """Update a symbol's status within a job."""
        job = self.get_job(job_id)
        if job is None:
            logger.error(f"Job {job_id} not found for update")
            return

        if symbol not in job.symbols_state:
            logger.error(f"Symbol {symbol} not in job {job_id}")
            return

        sym_state = job.symbols_state[symbol]
        sym_state.status = status

        for key, value in kwargs.items():
            if hasattr(sym_state, key):
                setattr(sym_state, key, value)

        if status == SymbolStatus.FETCHING and sym_state.started_at is None:
            sym_state.started_at = datetime.utcnow()

        if status in (SymbolStatus.COMPLETED, SymbolStatus.FAILED):
            sym_state.completed_at = datetime.utcnow()

        job.updated_at = datetime.utcnow()
        job.status = job.compute_status()
        self._save(job)

    def increment_chunk(self, job_id: str, symbol: str) -> None:
        """Increment the completed chunk count for a symbol."""
        job = self.get_job(job_id)
        if job and symbol in job.symbols_state:
            job.symbols_state[symbol].completed_chunks += 1
            job.updated_at = datetime.utcnow()
            self._save(job)

    def increment_requests(self, job_id: str, count: int = 1) -> None:
        """Increment the global request counter for the job."""
        job = self.get_job(job_id)
        if job:
            job.total_requests += count
            job.updated_at = datetime.utcnow()
            self._save(job)

    def set_retry_info(self, job_id: str, symbol: str, attempt: int, reason: str, wait: float) -> None:
        """Update retry information for a symbol."""
        from rsi_supertrend_backtester.data_collection.models.job import RetryInfo
        job = self.get_job(job_id)
        if job and symbol in job.symbols_state:
            job.symbols_state[symbol].retry_info = RetryInfo(
                attempt=attempt,
                max_attempts=settings.max_retries,
                reason=reason,
                wait_seconds=wait,
            )
            self._save(job)

    def clear_retry_info(self, job_id: str, symbol: str) -> None:
        """Clear retry info once symbol recovers."""
        job = self.get_job(job_id)
        if job and symbol in job.symbols_state:
            job.symbols_state[symbol].retry_info = None
            self._save(job)

    def mark_job_failed(self, job_id: str, reason: str) -> None:
        """Mark entire job as failed (e.g., on auth error)."""
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.FAILED
            for sym_state in job.symbols_state.values():
                if sym_state.status not in (SymbolStatus.COMPLETED, SymbolStatus.FAILED, SymbolStatus.CANCELLED):
                    sym_state.status = SymbolStatus.FAILED
                    sym_state.error = reason
                    sym_state.completed_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            self._save(job)

    def cancel_job(self, job_id: str) -> None:
        """Forcefully cancel an active job and all its pending symbols."""
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.CANCELLED
            for sym_state in job.symbols_state.values():
                if sym_state.status not in (SymbolStatus.COMPLETED, SymbolStatus.FAILED, SymbolStatus.CANCELLED):
                    sym_state.status = SymbolStatus.CANCELLED
                    sym_state.error = "Cancelled by user"
                    sym_state.completed_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            self._save(job)

    def _job_path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"

    def _save(self, job: Job) -> None:
        """Persist job to disk."""
        path = self._job_path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(job.model_dump_json(indent=2))


# Module-level singleton
job_manager = JobManager()
