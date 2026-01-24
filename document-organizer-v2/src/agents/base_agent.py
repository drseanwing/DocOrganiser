"""
Base Agent class for Document Organizer v2.

All processing agents inherit from this base class which provides:
- Database connection management
- Logging setup
- Common utilities
- Progress tracking
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Any, TypeVar, Generic
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from src.config import Settings, get_settings, ProcessingPhase


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


T = TypeVar('T')


class AgentResult(Generic[T]):
    """Result container for agent operations."""
    
    def __init__(
        self,
        success: bool,
        data: Optional[T] = None,
        error: Optional[str] = None,
        processed_count: int = 0,
        skipped_count: int = 0,
        error_count: int = 0,
        duration_seconds: float = 0.0,
        metadata: Optional[dict] = None
    ):
        self.success = success
        self.data = data
        self.error = error
        self.processed_count = processed_count
        self.skipped_count = skipped_count
        self.error_count = error_count
        self.duration_seconds = duration_seconds
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> dict:
        """Convert result to dictionary for logging/storage."""
        return {
            "success": self.success,
            "error": self.error,
            "processed_count": self.processed_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "duration_seconds": self.duration_seconds,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }


class BaseAgent(ABC):
    """
    Abstract base class for all processing agents.
    
    Provides:
    - Database session management
    - Structured logging
    - Progress tracking
    - Error handling utilities
    """
    
    # Agent identification
    AGENT_NAME: str = "base"
    AGENT_PHASE: ProcessingPhase = ProcessingPhase.PENDING
    
    def __init__(self, settings: Optional[Settings] = None, job_id: Optional[str] = None):
        """
        Initialize the agent.
        
        Args:
            settings: Configuration settings (uses global if not provided)
            job_id: Processing job ID for tracking
        """
        self.settings = settings or get_settings()
        self.job_id = job_id
        
        # Setup logging
        self.logger = structlog.get_logger(self.AGENT_NAME)
        self._setup_file_logging()
        
        # Database engine (lazy initialization)
        self._engine = None
        self._session_factory = None
        
        # Progress tracking
        self.total_items = 0
        self.processed_items = 0
        self.current_item: Optional[str] = None
        self._start_time: Optional[datetime] = None
    
    def _setup_file_logging(self):
        """Setup file logging if configured."""
        if self.settings.log_file:
            file_handler = logging.FileHandler(self.settings.log_file)
            file_handler.setLevel(getattr(logging, self.settings.log_level.upper()))
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            )
            logging.getLogger(self.AGENT_NAME).addHandler(file_handler)
    
    @property
    def engine(self):
        """Lazy-load database engine."""
        if self._engine is None:
            self._engine = create_engine(
                self.settings.database_url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10
            )
        return self._engine
    
    @property
    def session_factory(self):
        """Lazy-load session factory."""
        if self._session_factory is None:
            self._session_factory = sessionmaker(bind=self.engine)
        return self._session_factory
    
    @asynccontextmanager
    async def get_session(self):
        """
        Context manager for database sessions.
        
        Usage:
            async with self.get_session() as session:
                result = session.execute(query)
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            self.logger.error("database_error", error=str(e))
            raise
        finally:
            session.close()
    
    def get_sync_session(self) -> Session:
        """Get a synchronous database session (caller must manage lifecycle)."""
        return self.session_factory()
    
    # -------------------------------------------------------------------------
    # Progress Tracking
    # -------------------------------------------------------------------------
    
    def start_processing(self, total_items: int = 0):
        """Mark the start of processing."""
        self._start_time = datetime.utcnow()
        self.total_items = total_items
        self.processed_items = 0
        self.logger.info(
            "agent_started",
            agent=self.AGENT_NAME,
            phase=self.AGENT_PHASE.value,
            job_id=self.job_id,
            total_items=total_items
        )
    
    def update_progress(self, current_item: str, increment: int = 1):
        """Update processing progress."""
        self.processed_items += increment
        self.current_item = current_item
        
        if self.total_items > 0:
            progress_pct = (self.processed_items / self.total_items) * 100
            self.logger.debug(
                "progress_update",
                current_item=current_item,
                processed=self.processed_items,
                total=self.total_items,
                progress_pct=f"{progress_pct:.1f}%"
            )
    
    def get_elapsed_seconds(self) -> float:
        """Get elapsed time since processing started."""
        if self._start_time is None:
            return 0.0
        return (datetime.utcnow() - self._start_time).total_seconds()
    
    # -------------------------------------------------------------------------
    # Job Tracking
    # -------------------------------------------------------------------------
    
    def update_job_phase(self, phase: ProcessingPhase, progress_pct: int = 0):
        """Update the processing job's current phase."""
        if not self.job_id:
            return
        
        session = self.get_sync_session()
        try:
            session.execute(
                text("""
                    UPDATE processing_jobs 
                    SET current_phase = :phase, 
                        progress_percent = :progress,
                        files_processed = :processed
                    WHERE id = :job_id
                """),
                {
                    "phase": phase.value,
                    "progress": progress_pct,
                    "processed": self.processed_items,
                    "job_id": self.job_id
                }
            )
            session.commit()
        finally:
            session.close()
    
    def log_to_db(
        self,
        action: str,
        document_id: Optional[int] = None,
        details: Optional[dict] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None
    ):
        """Log an action to the processing_log table."""
        session = self.get_sync_session()
        try:
            import json
            session.execute(
                text("""
                    INSERT INTO processing_log 
                    (document_id, batch_id, action, phase, details, success, error_message, duration_ms)
                    VALUES 
                    (:doc_id, :batch_id, :action, :phase, :details::jsonb, :success, :error, :duration)
                """),
                {
                    "doc_id": document_id,
                    "batch_id": self.job_id,
                    "action": action,
                    "phase": self.AGENT_PHASE.value,
                    "details": json.dumps(details) if details else None,
                    "success": success,
                    "error": error_message,
                    "duration": duration_ms
                }
            )
            session.commit()
        except Exception as e:
            self.logger.warning("log_to_db_failed", error=str(e))
            session.rollback()
        finally:
            session.close()
    
    # -------------------------------------------------------------------------
    # Abstract Methods
    # -------------------------------------------------------------------------
    
    @abstractmethod
    async def run(self, **kwargs) -> AgentResult:
        """
        Execute the agent's main processing logic.
        
        Must be implemented by subclasses.
        
        Returns:
            AgentResult with processing outcome
        """
        pass
    
    @abstractmethod
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """
        Validate that prerequisites for this agent are met.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        pass
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    async def safe_execute(self, func, *args, default=None, **kwargs) -> Any:
        """
        Safely execute a function with error handling.
        
        Args:
            func: Function to execute
            *args: Positional arguments
            default: Default value on error
            **kwargs: Keyword arguments
            
        Returns:
            Function result or default value
        """
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            self.logger.warning(
                "safe_execute_error",
                function=func.__name__,
                error=str(e)
            )
            return default
    
    def chunk_list(self, items: list, chunk_size: int) -> list[list]:
        """Split a list into chunks of specified size."""
        return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
    
    async def cleanup(self):
        """Cleanup resources. Override in subclasses if needed."""
        if self._engine:
            self._engine.dispose()
        self.logger.info("agent_cleanup_complete", agent=self.AGENT_NAME)
