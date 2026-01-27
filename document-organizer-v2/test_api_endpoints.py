"""
Unit tests for Document Organizer v2 API endpoints.

Tests the FastAPI server endpoints with mocked dependencies.
"""

import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
import tempfile
import json

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import test dependencies
from fastapi.testclient import TestClient


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_settings():
    """Provide mock settings for API tests."""
    class MockSettings:
        postgres_host = "localhost"
        postgres_port = 5432
        postgres_db = "document_organizer_test"
        postgres_user = "test_user"
        postgres_password = "test_password"
        database_url = "postgresql://test_user:test_password@localhost:5432/document_organizer_test"
        data_input_path = "/data/input"
        data_source_path = "/data/source"
        data_working_path = "/data/working"
        data_output_path = "/data/output"
        data_reports_path = "/data/reports"
        api_key = None  # No API key for tests (development mode)
        cors_origins = "http://localhost:3000"
        rate_limit = "100/minute"
        callback_url = None

    return MockSettings()


@pytest.fixture
def mock_engine():
    """Provide a mock database engine."""
    engine = MagicMock()
    mock_conn = MagicMock()
    mock_result = MagicMock()

    # Setup context manager for connection
    engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=None)

    mock_conn.execute.return_value = mock_result
    mock_result.scalar.return_value = "test-job-id-123"
    mock_result.fetchone.return_value = None

    return engine


@pytest.fixture
def client(mock_settings, mock_engine):
    """Provide a test client for the FastAPI app."""
    with patch('src.api.server.get_settings', return_value=mock_settings):
        with patch('src.api.server.get_engine', return_value=mock_engine):
            # Import after patching
            from src.api.server import app
            yield TestClient(app)


@pytest.fixture
def authenticated_client(mock_settings, mock_engine):
    """Provide a test client with API key authentication enabled."""
    mock_settings.api_key = "test-api-key-12345"

    with patch('src.api.server.get_settings', return_value=mock_settings):
        with patch('src.api.server.get_engine', return_value=mock_engine):
            from src.api.server import app
            yield TestClient(app)


# ============================================================================
# Health Check Tests
# ============================================================================

class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check_returns_200(self, client):
        """Test that health check returns 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_check_returns_status(self, client):
        """Test that health check returns expected status."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "2.0.0"

    def test_health_check_returns_timestamp(self, client):
        """Test that health check returns timestamp."""
        response = client.get("/health")
        data = response.json()
        assert "timestamp" in data


# ============================================================================
# Job Trigger Tests
# ============================================================================

class TestJobTriggerEndpoint:
    """Tests for the /webhook/job endpoint."""

    def test_trigger_job_requires_source_path(self, client):
        """Test that triggering a job requires source_path."""
        response = client.post("/webhook/job", json={})
        assert response.status_code == 422  # Validation error

    def test_trigger_job_validates_path_exists(self, client):
        """Test that non-existent path returns 400."""
        response = client.post("/webhook/job", json={
            "source_path": "/nonexistent/path/test.zip"
        })
        assert response.status_code == 400

    def test_trigger_job_validates_zip_extension(self, client):
        """Test that non-ZIP files are rejected."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test content")
            temp_path = f.name

        # Need to mock path validation for this test
        response = client.post("/webhook/job", json={
            "source_path": temp_path
        })
        # Should fail because it's not a ZIP and likely outside allowed paths
        assert response.status_code == 400

        Path(temp_path).unlink()

    def test_trigger_job_path_traversal_blocked(self, client):
        """Test that path traversal attempts are blocked."""
        response = client.post("/webhook/job", json={
            "source_path": "/data/input/../../../etc/passwd"
        })
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"].lower()


# ============================================================================
# Job Status Tests
# ============================================================================

class TestJobStatusEndpoint:
    """Tests for the /jobs/{job_id}/status endpoint."""

    def test_status_job_not_found(self, client, mock_engine):
        """Test that non-existent job returns 404."""
        # Setup mock to return None
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        response = client.get("/jobs/nonexistent-job-id/status")
        assert response.status_code == 404

    def test_status_returns_job_details(self, client, mock_engine):
        """Test that status endpoint returns job details."""
        # Setup mock to return job data
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (
            "test-job-123",
            "processing",
            "indexing",
            "/data/input/test.zip",
            150,
            datetime.now(),
            None,
            None
        )
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        response = client.get("/jobs/test-job-123/status")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "test-job-123"
        assert data["status"] == "processing"
        assert data["current_phase"] == "indexing"


# ============================================================================
# Job Approval Tests
# ============================================================================

class TestJobApprovalEndpoint:
    """Tests for the /jobs/{job_id}/approve endpoint."""

    def test_approve_job_not_found(self, client, mock_engine):
        """Test that approving non-existent job returns 404."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        response = client.post("/jobs/nonexistent/approve", json={
            "approved": True
        })
        assert response.status_code == 404

    def test_approve_job_wrong_status(self, client, mock_engine):
        """Test that approving job in wrong status returns 400."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("completed", "completed")
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        response = client.post("/jobs/test-job/approve", json={
            "approved": True
        })
        assert response.status_code == 400
        assert "not awaiting approval" in response.json()["detail"].lower()

    def test_cancel_job(self, client, mock_engine):
        """Test that declining approval cancels the job."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("review_required", "review_required")
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        response = client.post("/jobs/test-job/approve", json={
            "approved": False
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"


# ============================================================================
# Job Report Tests
# ============================================================================

class TestJobReportEndpoint:
    """Tests for the /jobs/{job_id}/report endpoint."""

    def test_report_job_not_found(self, client, mock_engine):
        """Test that report for non-existent job returns 404."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        response = client.get("/jobs/nonexistent/report")
        assert response.status_code == 404

    def test_report_returns_statistics(self, client, mock_engine):
        """Test that report returns job statistics."""
        mock_conn = MagicMock()

        # First call returns job status
        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = ("completed",)

        # Subsequent calls return statistics
        mock_result2 = MagicMock()
        mock_result2.scalar.return_value = 100  # total_files

        mock_result3 = MagicMock()
        mock_result3.scalar.return_value = 5  # duplicate_groups

        mock_result4 = MagicMock()
        mock_result4.scalar.return_value = 10  # shortcuts_planned

        mock_result5 = MagicMock()
        mock_result5.scalar.return_value = 25  # pending_changes

        mock_conn.execute.side_effect = [
            mock_result1, mock_result2, mock_result3, mock_result4, mock_result5
        ]
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        response = client.get("/jobs/test-job/report")
        assert response.status_code == 200
        data = response.json()
        assert "total_files" in data
        assert "duplicate_groups" in data


# ============================================================================
# Authentication Tests
# ============================================================================

class TestAPIAuthentication:
    """Tests for API authentication."""

    def test_no_api_key_in_dev_mode(self, client):
        """Test that requests work without API key in dev mode."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_missing_api_key_when_required(self, authenticated_client):
        """Test that missing API key returns 401 when required."""
        response = authenticated_client.get("/jobs/test-job/status")
        assert response.status_code == 401
        assert "API key required" in response.json()["detail"]

    def test_invalid_api_key(self, authenticated_client):
        """Test that invalid API key returns 403."""
        response = authenticated_client.get(
            "/jobs/test-job/status",
            headers={"X-API-Key": "wrong-key"}
        )
        assert response.status_code == 403
        assert "Invalid API key" in response.json()["detail"]

    def test_valid_api_key(self, authenticated_client, mock_engine):
        """Test that valid API key allows access."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        response = authenticated_client.get(
            "/jobs/test-job/status",
            headers={"X-API-Key": "test-api-key-12345"}
        )
        # Should get 404 (job not found), not 401/403
        assert response.status_code == 404


# ============================================================================
# Path Validation Tests
# ============================================================================

class TestPathValidation:
    """Tests for path validation security."""

    def test_absolute_path_traversal_blocked(self, client):
        """Test that absolute path traversal is blocked."""
        response = client.post("/webhook/job", json={
            "source_path": "/etc/passwd"
        })
        assert response.status_code == 400

    def test_relative_path_traversal_blocked(self, client):
        """Test that relative path traversal is blocked."""
        response = client.post("/webhook/job", json={
            "source_path": "/data/input/../../etc/passwd"
        })
        assert response.status_code == 400

    def test_symlink_escape_blocked(self, client):
        """Test that symlink escape attempts are handled."""
        response = client.post("/webhook/job", json={
            "source_path": "/data/input/link_to_outside/../../../etc/passwd"
        })
        assert response.status_code == 400


# ============================================================================
# Main Test Runner
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Document Organizer v2 - API Endpoint Tests")
    print("=" * 60)
    print()

    # Run all tests
    import unittest

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    for test_class in [
        TestHealthEndpoint,
        TestJobTriggerEndpoint,
        TestJobStatusEndpoint,
        TestJobApprovalEndpoint,
        TestJobReportEndpoint,
        TestAPIAuthentication,
        TestPathValidation,
    ]:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print()
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 60)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
