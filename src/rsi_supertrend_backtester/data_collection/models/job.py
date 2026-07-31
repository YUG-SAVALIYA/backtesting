"""
Pydantic models for job state management.
"""
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
import uuid


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"  # Some symbols succeeded, some failed


class SymbolStatus(str, Enum):
    QUEUED = "queued"
    RESOLVING = "resolving"
    FETCHING = "fetching"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetryInfo(BaseModel):
    attempt: int
    max_attempts: int
    reason: str
    wait_seconds: float


class SymbolState(BaseModel):
    symbol: str
    status: SymbolStatus = SymbolStatus.QUEUED
    security_id: str | None = None
    total_chunks: int = 0
    completed_chunks: int = 0
    total_rows_5min: int = 0
    total_rows_day: int = 0
    total_rows_week: int = 0
    files: list[str] = Field(default_factory=list)
    error: str | None = None
    retry_info: RetryInfo | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Input parameters
    symbols: list[str]
    from_date: str
    to_date: str
    exchange_segment: str
    instrument: str

    # Execution state
    total_requests: int = 0
    symbols_state: dict[str, SymbolState] = Field(default_factory=dict)

    def total_symbols(self) -> int:
        return len(self.symbols)

    def completed_symbols(self) -> int:
        return sum(
            1
            for s in self.symbols_state.values()
            if s.status == SymbolStatus.COMPLETED
        )

    def failed_symbols(self) -> int:
        return sum(
            1
            for s in self.symbols_state.values()
            if s.status == SymbolStatus.FAILED
        )

    def is_done(self) -> bool:
        if not self.symbols_state:
            return False
        return all(
            s.status in (SymbolStatus.COMPLETED, SymbolStatus.FAILED, SymbolStatus.CANCELLED)
            for s in self.symbols_state.values()
        )

    def compute_status(self) -> JobStatus:
        if self.status == JobStatus.CANCELLED:
            return JobStatus.CANCELLED
        if not self.symbols_state:
            return JobStatus.QUEUED
        statuses = {s.status for s in self.symbols_state.values()}
        if all(s in (SymbolStatus.COMPLETED, SymbolStatus.FAILED, SymbolStatus.CANCELLED) for s in statuses):
            if any(s == SymbolStatus.CANCELLED for s in statuses):
                return JobStatus.CANCELLED
            if any(s == SymbolStatus.FAILED for s in statuses):
                if any(s == SymbolStatus.COMPLETED for s in statuses):
                    return JobStatus.PARTIAL
                return JobStatus.FAILED
            return JobStatus.COMPLETED
        if any(s == SymbolStatus.FETCHING for s in statuses):
            return JobStatus.RUNNING
        return JobStatus.QUEUED


# ─── API Request / Response schemas ──────────────────────────────────────────


class SymbolCandidate(BaseModel):
    security_id: str
    trading_symbol: str
    exchange: str
    instrument_type: str


class ValidateSymbolsRequest(BaseModel):
    symbols: list[str]
    exchange_segment: str = "NSE_EQ"
    instrument: str = "EQUITY"


class ValidateSymbolsResponse(BaseModel):
    resolved: dict[str, SymbolCandidate]
    ambiguous: dict[str, list[SymbolCandidate]]
    not_found: list[str]


class CreateJobRequest(BaseModel):
    symbols: list[str]
    from_date: str
    to_date: str
    exchange_segment: str = "NSE_EQ"
    instrument: str = "EQUITY"
    symbol_resolutions: dict[str, str] = Field(
        default_factory=dict
    )  # symbol → securityId override


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    symbols: list[str]


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    total_symbols: int
    completed_symbols: int
    failed_symbols: int
    total_requests: int
    symbols: dict[str, SymbolState]


class FileInfo(BaseModel):
    filename: str
    symbol: str
    timeframe: str  # 5min, Day, Week
    path: str
    size_bytes: int


class JobFilesResponse(BaseModel):
    job_id: str
    files: list[FileInfo]
    total_files: int
