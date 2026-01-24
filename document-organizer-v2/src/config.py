"""
Configuration management for Document Organizer v2.

Uses pydantic-settings for type-safe configuration with environment variable support.
"""

from enum import Enum
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VersionArchiveStrategy(str, Enum):
    """Strategy for archiving superseded document versions."""
    SUBFOLDER = "subfolder"      # /doc/_versions/doc_v1.docx
    INLINE = "inline"            # /doc_v1.docx alongside /doc.docx
    SEPARATE_ARCHIVE = "archive" # /Archive/Versions/doc_v1.docx


class DuplicateAction(str, Enum):
    """Actions for handling duplicate files."""
    KEEP_PRIMARY = "keep_primary"
    SHORTCUT = "shortcut"
    KEEP_BOTH = "keep_both"
    DELETE = "delete"


class ProcessingPhase(str, Enum):
    """Processing phases for job tracking."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    INDEXING = "indexing"
    SUMMARIZING = "summarizing"
    DEDUPLICATING = "deduplicating"
    VERSIONING = "versioning"
    ORGANIZING = "organizing"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    EXECUTING = "executing"
    PACKAGING = "packaging"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # -------------------------------------------------------------------------
    # Database Configuration
    # -------------------------------------------------------------------------
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_db: str = Field(default="document_organizer", description="Database name")
    postgres_user: str = Field(default="doc_organizer", description="Database user")
    postgres_password: str = Field(default="changeme", description="Database password")
    
    @property
    def database_url(self) -> str:
        """Construct database connection URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    # -------------------------------------------------------------------------
    # Ollama Configuration
    # -------------------------------------------------------------------------
    ollama_host: str = Field(default="http://localhost:11434", description="Ollama API URL")
    ollama_model: str = Field(default="llama3.2", description="Ollama model for summarization")
    ollama_timeout: int = Field(default=120, description="Ollama request timeout (seconds)")
    ollama_temperature: float = Field(default=0.3, description="Ollama temperature for responses")
    
    # -------------------------------------------------------------------------
    # Claude Configuration
    # -------------------------------------------------------------------------
    anthropic_api_key: Optional[str] = Field(default=None, description="Anthropic API key")
    claude_model: str = Field(default="claude-sonnet-4-20250514", description="Claude model for organization")
    claude_max_tokens: int = Field(default=16000, description="Max tokens for Claude response")
    
    # -------------------------------------------------------------------------
    # Processing Configuration
    # -------------------------------------------------------------------------
    batch_size: int = Field(default=50, description="Files to process per batch")
    max_file_size_mb: int = Field(default=100, description="Skip files larger than this (MB)")
    supported_extensions: list[str] = Field(
        default=["pdf", "docx", "xlsx", "pptx", "txt", "md", "csv", "html", "json", "xml"],
        description="File extensions to process"
    )
    
    # -------------------------------------------------------------------------
    # Duplicate Detection
    # -------------------------------------------------------------------------
    auto_approve_shortcuts: bool = Field(
        default=False, 
        description="Auto-approve shortcut creation for exact duplicates"
    )
    min_duplicate_size_kb: int = Field(
        default=10, 
        description="Only flag duplicates larger than this (KB)"
    )
    
    # -------------------------------------------------------------------------
    # Version Control
    # -------------------------------------------------------------------------
    version_archive_strategy: VersionArchiveStrategy = Field(
        default=VersionArchiveStrategy.SUBFOLDER,
        description="How to archive superseded versions"
    )
    version_folder_name: str = Field(
        default="_versions",
        description="Name of version archive subfolder"
    )
    
    # Patterns for detecting version markers in filenames
    version_patterns: list[str] = Field(
        default=[
            r"_v(\d+)",           # _v1, _v2
            r"_rev(\d+)",         # _rev1, _rev2
            r"_version(\d+)",     # _version1
            r"\s*\((\d+)\)",      # (1), (2)
            r"_(\d{4}-\d{2}-\d{2})", # _2024-01-15
            r"_(draft|final|approved|review)", # Status markers
        ],
        description="Regex patterns for version markers"
    )
    
    # -------------------------------------------------------------------------
    # Safety & Review
    # -------------------------------------------------------------------------
    review_required: bool = Field(
        default=True,
        description="Require human review before executing changes"
    )
    dry_run: bool = Field(
        default=False,
        description="Simulate changes without modifying files"
    )
    
    # -------------------------------------------------------------------------
    # Paths
    # -------------------------------------------------------------------------
    data_input_path: str = Field(default="/data/input", description="Input ZIP directory")
    data_source_path: str = Field(default="/data/source", description="Extracted source files")
    data_working_path: str = Field(default="/data/working", description="Reorganized files")
    data_output_path: str = Field(default="/data/output", description="Output ZIP directory")
    data_reports_path: str = Field(default="/data/reports", description="Processing reports")
    
    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: Optional[str] = Field(default=None, description="Log file path (optional)")
    
    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------
    callback_url: Optional[str] = Field(
        default=None,
        description="Webhook URL to call on completion"
    )
    
    # -------------------------------------------------------------------------
    # Computed Properties
    # -------------------------------------------------------------------------
    @property
    def max_file_size_bytes(self) -> int:
        """Max file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024
    
    @property
    def min_duplicate_size_bytes(self) -> int:
        """Min duplicate size in bytes."""
        return self.min_duplicate_size_kb * 1024


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the current settings instance."""
    return settings


def reload_settings() -> Settings:
    """Reload settings from environment."""
    global settings
    settings = Settings()
    return settings
