"""
Shared pytest fixtures for Document Organizer v2 tests.

Provides common test fixtures for database mocking, settings, temp directories,
and service mocking across all test modules.
"""

import sys
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))


# -------------------------------------------------------------------------
# Settings Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def test_settings():
    """
    Provide test configuration settings.

    Returns a mock Settings object with default test values for all agents.
    """
    class MockSettings:
        # Database
        postgres_host = "localhost"
        postgres_port = 5432
        postgres_db = "document_organizer_test"
        postgres_user = "test_user"
        postgres_password = "test_password"
        database_url = "postgresql://test_user:test_password@localhost:5432/document_organizer_test"

        # Paths
        data_input_path = "/data/test/input"
        data_source_path = "/data/test/source"
        data_working_path = "/data/test/working"
        data_output_path = "/data/test/output"
        data_reports_path = "/data/test/reports"

        # Ollama
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3.2"
        ollama_timeout = 120
        ollama_temperature = 0.3

        # Claude
        anthropic_api_key = "test-api-key"
        claude_model = "claude-sonnet-4-20250514"
        claude_max_tokens = 16000

        # Processing
        batch_size = 50
        max_file_size_mb = 100
        max_file_size_bytes = 100 * 1024 * 1024
        supported_extensions = ["pdf", "docx", "xlsx", "pptx", "txt", "md"]

        # Deduplication
        auto_approve_shortcuts = False
        min_duplicate_size_kb = 10
        min_duplicate_size_bytes = 10 * 1024

        # Version control
        version_archive_strategy = "subfolder"
        version_folder_name = "_versions"
        version_patterns = [
            r"_v(\d+)",
            r"_rev(\d+)",
            r"_version(\d+)",
            r"\s*\((\d+)\)",
            r"_(\d{4}-\d{2}-\d{2})",
            r"_(draft|final|approved|review)",
        ]

        # Safety
        review_required = True
        dry_run = False

        # Logging
        log_file = None
        log_level = "INFO"

        # Callbacks
        callback_url = None

        # API Security
        api_key = None
        cors_origins = "http://localhost:3000"
        rate_limit = "100/minute"

    return MockSettings()


# -------------------------------------------------------------------------
# Database Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def mock_session():
    """
    Provide a mock SQLAlchemy session.

    Returns a MagicMock configured to behave like a database session with
    common query patterns.
    """
    session = MagicMock()

    # Setup common query patterns
    mock_query = MagicMock()
    session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.filter_by.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.offset.return_value = mock_query
    mock_query.first.return_value = None
    mock_query.all.return_value = []
    mock_query.count.return_value = 0

    # Setup execute() for raw SQL
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_result.scalars.return_value = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result

    # Setup transaction methods
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    session.add = MagicMock()
    session.flush = MagicMock()

    return session


# -------------------------------------------------------------------------
# Temporary Directory Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def temp_dir():
    """
    Provide a temporary directory for test files.

    Creates a temporary directory that is automatically cleaned up after the test.
    Returns a pathlib.Path object.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# -------------------------------------------------------------------------
# Sample Data Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def sample_documents():
    """
    Provide sample document data for testing.

    Returns a list of dictionaries representing indexed documents with typical
    metadata fields.
    """
    return [
        {
            "id": 1,
            "current_path": "/data/source/Documents/Report.docx",
            "file_name": "Report.docx",
            "file_extension": "docx",
            "file_size_bytes": 52000,
            "content_hash": "abc123def456",
            "source_modified_at": datetime(2024, 1, 15, 10, 30),
            "indexed_at": datetime(2024, 1, 20, 9, 0),
            "summary": "Q1 financial report",
            "suggested_category": "Finance/Reports",
        },
        {
            "id": 2,
            "current_path": "/data/source/Downloads/Report.docx",
            "file_name": "Report.docx",
            "file_extension": "docx",
            "file_size_bytes": 52000,
            "content_hash": "abc123def456",  # Same hash - duplicate
            "source_modified_at": datetime(2024, 1, 10, 14, 20),
            "indexed_at": datetime(2024, 1, 20, 9, 1),
            "summary": "Q1 financial report",
            "suggested_category": "Finance/Reports",
        },
        {
            "id": 3,
            "current_path": "/data/source/Projects/Budget.xlsx",
            "file_name": "Budget.xlsx",
            "file_extension": "xlsx",
            "file_size_bytes": 128000,
            "content_hash": "xyz789uvw012",
            "source_modified_at": datetime(2024, 1, 18, 11, 45),
            "indexed_at": datetime(2024, 1, 20, 9, 2),
            "summary": "2024 budget planning",
            "suggested_category": "Finance/Planning",
        },
        {
            "id": 4,
            "current_path": "/data/source/Archive/Budget_v1.xlsx",
            "file_name": "Budget_v1.xlsx",
            "file_extension": "xlsx",
            "file_size_bytes": 115000,
            "content_hash": "xyz789uvw000",  # Different hash - version
            "source_modified_at": datetime(2024, 1, 12, 9, 15),
            "indexed_at": datetime(2024, 1, 20, 9, 3),
            "summary": "2024 budget planning draft",
            "suggested_category": "Finance/Planning",
        },
        {
            "id": 5,
            "current_path": "/data/source/Photos/vacation.jpg",
            "file_name": "vacation.jpg",
            "file_extension": "jpg",
            "file_size_bytes": 2400000,
            "content_hash": "img456photo789",
            "source_modified_at": datetime(2023, 12, 25, 16, 30),
            "indexed_at": datetime(2024, 1, 20, 9, 4),
            "summary": None,  # Not processed
            "suggested_category": "Personal/Photos",
        },
    ]


@pytest.fixture
def job_id():
    """
    Provide a test job ID (UUID).

    Returns a string UUID for testing job tracking.
    """
    return str(uuid4())


# -------------------------------------------------------------------------
# Service Mocking Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def mock_ollama():
    """
    Provide a mock Ollama service.

    Returns a mock OllamaService with async methods configured for testing.
    """
    mock_service = MagicMock()
    mock_service.base_url = "http://localhost:11434"
    mock_service.model = "llama3.2"
    mock_service.timeout = 120
    mock_service.temperature = 0.3

    # Mock health_check as async
    mock_service.health_check = AsyncMock(return_value=True)

    # Mock generate as async
    async def mock_generate(prompt, system_prompt=None, max_retries=3):
        """Mock generate that returns test response."""
        return "This is a test summary generated by mock Ollama."

    mock_service.generate = AsyncMock(side_effect=mock_generate)

    # Mock chat as async
    async def mock_chat(messages, max_retries=3):
        """Mock chat that returns test response."""
        return "This is a test chat response from mock Ollama."

    mock_service.chat = AsyncMock(side_effect=mock_chat)

    return mock_service


@pytest.fixture
def mock_claude():
    """
    Provide a mock Claude service.

    Returns a mock ClaudeService with async methods configured for testing.
    """
    mock_service = MagicMock()
    mock_service.api_key = "test-api-key"
    mock_service.model = "claude-sonnet-4-20250514"
    mock_service.max_tokens = 16000
    mock_service.base_url = "https://api.anthropic.com/v1/messages"

    # Mock is_configured
    mock_service.is_configured = MagicMock(return_value=True)

    # Mock health_check as async
    mock_service.health_check = AsyncMock(return_value=True)

    # Mock generate as async
    async def mock_generate(prompt, system_prompt=None, max_retries=3):
        """Mock generate that returns test response."""
        return "This is a test response from mock Claude."

    mock_service.generate = AsyncMock(side_effect=mock_generate)

    # Mock generate_json as async
    async def mock_generate_json(prompt, system_prompt=None, max_retries=3):
        """Mock generate_json that returns test JSON."""
        return {
            "category": "Finance/Reports",
            "suggested_filename": "2024_Q1_Financial_Report.docx",
            "confidence": 0.95
        }

    mock_service.generate_json = AsyncMock(side_effect=mock_generate_json)

    return mock_service


# -------------------------------------------------------------------------
# Pytest Configuration
# -------------------------------------------------------------------------

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers",
        "asyncio: mark test as requiring asyncio support"
    )
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration test (requires services)"
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow running"
    )
