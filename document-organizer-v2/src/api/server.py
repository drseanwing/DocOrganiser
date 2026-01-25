"""
FastAPI server for Document Organizer v2 webhook endpoints.

Provides HTTP API for triggering document processing jobs and checking status.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from src.config import get_settings, ProcessingPhase
from src.main import DocumentOrganizer


# Configure logging
logger = structlog.get_logger("api")

# Create FastAPI app
app = FastAPI(
    title="Document Organizer v2 API",
    description="Webhook endpoints for document organization pipeline",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database engine (lazy-loaded)
_engine = None


def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url)
    return _engine


# ============================================================================
# Pydantic Models
# ============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Health status")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Current server time")


class JobTriggerRequest(BaseModel):
    """Request to trigger a new processing job."""
    source_path: str = Field(..., description="Path to input ZIP file")
    skip_phases: Optional[list[str]] = Field(default=None, description="Phases to skip (for resuming)")
    dry_run: Optional[bool] = Field(default=None, description="Simulate changes without executing")


class JobTriggerResponse(BaseModel):
    """Response from job trigger."""
    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(..., description="Initial job status")
    message: str = Field(..., description="Human-readable message")


class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="Current job status")
    current_phase: str = Field(..., description="Current processing phase")
    source_path: Optional[str] = Field(None, description="Source ZIP path")
    source_file_count: Optional[int] = Field(None, description="Number of files in source")
    started_at: Optional[datetime] = Field(None, description="Job start time")
    completed_at: Optional[datetime] = Field(None, description="Job completion time")
    error_message: Optional[str] = Field(None, description="Error message if failed")


class JobApprovalRequest(BaseModel):
    """Request to approve job execution."""
    approved: bool = Field(..., description="Whether to approve execution")
    comment: Optional[str] = Field(None, description="Optional approval comment")


class JobApprovalResponse(BaseModel):
    """Response from job approval."""
    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="New job status")
    message: str = Field(..., description="Human-readable message")


class JobReportResponse(BaseModel):
    """Job processing report."""
    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="Job status")
    total_files: int = Field(..., description="Total files indexed")
    duplicate_groups: int = Field(..., description="Number of duplicate groups found")
    shortcuts_planned: int = Field(..., description="Number of shortcuts to create")
    pending_changes: int = Field(..., description="Number of pending file changes")
    report_html_path: Optional[str] = Field(None, description="Path to HTML report")


# ============================================================================
# Background Task Processing
# ============================================================================

async def process_job_async(job_id: str, source_path: str, skip_phases: Optional[list[str]] = None):
    """
    Background task to process a job.

    Args:
        job_id: Job identifier
        source_path: Path to input ZIP file
        skip_phases: Phases to skip
    """
    try:
        logger.info("background_job_started", job_id=job_id, source_path=source_path)

        organizer = DocumentOrganizer()
        result = await organizer.process_zip(
            zip_path=source_path,
            job_id=job_id,
            skip_phases=skip_phases or []
        )

        logger.info("background_job_completed", job_id=job_id, result=result)

        # TODO: Call callback URL if configured
        settings = get_settings()
        if settings.callback_url:
            # Would make HTTP POST to callback_url with result
            pass

    except Exception as e:
        logger.error("background_job_failed", job_id=job_id, error=str(e))


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint.

    Returns server status and version information.
    """
    return HealthResponse(
        status="healthy",
        version="2.0.0"
    )


@app.post("/webhook/job", response_model=JobTriggerResponse, tags=["Jobs"])
async def trigger_job(
    request: JobTriggerRequest,
    background_tasks: BackgroundTasks
):
    """
    Trigger a new document processing job.

    Accepts a source ZIP path and starts processing in the background.
    Returns immediately with a job_id for status tracking.

    Args:
        request: Job trigger request with source_path
        background_tasks: FastAPI background tasks

    Returns:
        Job trigger response with job_id
    """
    # Validate source path exists
    source_path = Path(request.source_path)
    if not source_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Source path does not exist: {request.source_path}"
        )

    if not source_path.is_file() or source_path.suffix.lower() != ".zip":
        raise HTTPException(
            status_code=400,
            detail=f"Source path must be a ZIP file: {request.source_path}"
        )

    try:
        # Create job record
        engine = get_engine()

        import hashlib
        sha256 = hashlib.sha256()
        with open(source_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        zip_hash = sha256.hexdigest()

        zip_size = source_path.stat().st_size

        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO processing_jobs (
                        source_type, source_path, source_zip_path, source_zip_hash,
                        source_total_size, status, current_phase
                    ) VALUES (
                        'webhook', :path, :zip_path, :hash,
                        :size, 'pending', 'pending'
                    )
                    RETURNING id
                """),
                {
                    "path": str(source_path),
                    "zip_path": str(source_path),
                    "hash": zip_hash,
                    "size": zip_size
                }
            )
            conn.commit()
            job_id = str(result.scalar())

        # Start background processing
        background_tasks.add_task(
            process_job_async,
            job_id=job_id,
            source_path=str(source_path),
            skip_phases=request.skip_phases
        )

        logger.info("job_triggered", job_id=job_id, source_path=str(source_path))

        return JobTriggerResponse(
            job_id=job_id,
            status="pending",
            message=f"Job {job_id} started. Processing in background."
        )

    except Exception as e:
        logger.error("job_trigger_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger job: {str(e)}"
        )


@app.get("/jobs/{job_id}/status", response_model=JobStatusResponse, tags=["Jobs"])
async def get_job_status(job_id: str):
    """
    Get the current status of a processing job.

    Args:
        job_id: Job identifier

    Returns:
        Job status information
    """
    try:
        engine = get_engine()

        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, status, current_phase, source_path, source_file_count,
                           started_at, completed_at, error_message
                    FROM processing_jobs
                    WHERE id = :job_id
                """),
                {"job_id": job_id}
            )
            row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Job not found: {job_id}"
            )

        return JobStatusResponse(
            job_id=str(row[0]),
            status=row[1],
            current_phase=row[2],
            source_path=row[3],
            source_file_count=row[4],
            started_at=row[5],
            completed_at=row[6],
            error_message=row[7]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("status_check_failed", job_id=job_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get job status: {str(e)}"
        )


@app.post("/jobs/{job_id}/approve", response_model=JobApprovalResponse, tags=["Jobs"])
async def approve_job(
    job_id: str,
    request: JobApprovalRequest,
    background_tasks: BackgroundTasks
):
    """
    Approve a job for execution.

    Jobs in 'review_required' status need approval before execution.

    Args:
        job_id: Job identifier
        request: Approval request
        background_tasks: FastAPI background tasks

    Returns:
        Approval response
    """
    try:
        engine = get_engine()

        # Check job exists and is in review_required state
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT status, current_phase FROM processing_jobs WHERE id = :job_id"),
                {"job_id": job_id}
            )
            row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Job not found: {job_id}"
            )

        status, phase = row[0], row[1]

        if status != "review_required":
            raise HTTPException(
                status_code=400,
                detail=f"Job is not awaiting approval. Current status: {status}"
            )

        if not request.approved:
            # Cancelled by user
            with engine.connect() as conn:
                conn.execute(
                    text("""
                        UPDATE processing_jobs
                        SET status = 'cancelled', current_phase = 'cancelled'
                        WHERE id = :job_id
                    """),
                    {"job_id": job_id}
                )
                conn.commit()

            return JobApprovalResponse(
                job_id=job_id,
                status="cancelled",
                message="Job cancelled by user"
            )

        # Approved - update status and continue processing
        with engine.connect() as conn:
            conn.execute(
                text("""
                    UPDATE processing_jobs
                    SET status = 'approved', current_phase = 'approved'
                    WHERE id = :job_id
                """),
                {"job_id": job_id}
            )
            conn.commit()

        # Continue processing in background
        async def continue_processing():
            organizer = DocumentOrganizer()
            organizer.job_id = job_id

            # Execute and package
            await organizer._update_job_status(ProcessingPhase.EXECUTING)
            await organizer._execute_changes()
            await organizer._update_job_status(ProcessingPhase.PACKAGING)
            output_path = await organizer._package_output()
            await organizer._update_job_status(ProcessingPhase.COMPLETED)

            logger.info("job_completed_after_approval", job_id=job_id, output_path=output_path)

        background_tasks.add_task(continue_processing)

        return JobApprovalResponse(
            job_id=job_id,
            status="approved",
            message="Job approved. Continuing execution."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("approval_failed", job_id=job_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to approve job: {str(e)}"
        )


@app.get("/jobs/{job_id}/report", response_model=JobReportResponse, tags=["Jobs"])
async def get_job_report(job_id: str):
    """
    Get processing report for a job.

    Returns statistics about the processing results.

    Args:
        job_id: Job identifier

    Returns:
        Job processing report
    """
    try:
        engine = get_engine()

        # Check job exists
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT status FROM processing_jobs WHERE id = :job_id"),
                {"job_id": job_id}
            )
            row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Job not found: {job_id}"
            )

        status = row[0]

        # Gather statistics
        with engine.connect() as conn:
            # Total files
            result = conn.execute(
                text("SELECT COUNT(*) FROM document_items WHERE is_deleted = FALSE")
            )
            total_files = result.scalar() or 0

            # Duplicates
            result = conn.execute(text("SELECT COUNT(*) FROM duplicate_groups"))
            duplicate_groups = result.scalar() or 0

            result = conn.execute(
                text("SELECT COUNT(*) FROM duplicate_members WHERE action = 'shortcut'")
            )
            shortcuts_planned = result.scalar() or 0

            # Pending changes
            result = conn.execute(
                text("""
                    SELECT COUNT(*) FROM document_items
                    WHERE has_name_change = TRUE OR has_path_change = TRUE
                """)
            )
            pending_changes = result.scalar() or 0

        # Check for HTML report
        settings = get_settings()
        report_path = Path(settings.data_reports_path) / f"{job_id}_review.html"
        report_html_path = str(report_path) if report_path.exists() else None

        return JobReportResponse(
            job_id=job_id,
            status=status,
            total_files=total_files,
            duplicate_groups=duplicate_groups,
            shortcuts_planned=shortcuts_planned,
            pending_changes=pending_changes,
            report_html_path=report_html_path
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("report_generation_failed", job_id=job_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate report: {str(e)}"
        )


# ============================================================================
# Startup/Shutdown Events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    logger.info("api_server_starting", version="2.0.0")

    # Verify database connection
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("database_connected")
    except Exception as e:
        logger.error("database_connection_failed", error=str(e))


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("api_server_shutting_down")

    global _engine
    if _engine:
        _engine.dispose()
        _engine = None
