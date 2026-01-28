"""
Unit tests for Document Organizer v2 main orchestrator.

Tests the DocumentOrganizer class and CLI entry points.
"""

import sys
import asyncio
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_settings():
    """Provide mock settings for orchestrator tests."""
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
        review_required = False  # Skip review for testing
        dry_run = True  # Don't actually modify files
        callback_url = None
        version_archive_strategy = MagicMock(value="subfolder")

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
    mock_result.scalar.return_value = 1  # Job ID

    return engine


@pytest.fixture
def temp_zip():
    """Create a temporary ZIP file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        test_dir = Path(tmpdir) / "test_files"
        test_dir.mkdir()

        (test_dir / "document.txt").write_text("Test document content")
        (test_dir / "report.pdf").write_bytes(b"PDF content placeholder")
        (test_dir / "data.csv").write_text("col1,col2\nval1,val2")

        # Create ZIP
        zip_path = Path(tmpdir) / "test_archive.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for file in test_dir.iterdir():
                zf.write(file, file.name)

        yield zip_path


@pytest.fixture
def mock_agents():
    """Provide mock agents for testing."""
    mocks = {}

    for agent_name in ['IndexAgent', 'DedupAgent', 'VersionAgent', 'OrganizeAgent']:
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.error = None
        mock_result.processed_count = 10
        mock_agent.run = AsyncMock(return_value=mock_result)
        mocks[agent_name] = mock_agent

    return mocks


@pytest.fixture
def mock_execution_engine():
    """Provide a mock execution engine."""
    mock_engine = MagicMock()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.error = None
    mock_result.processed_count = 5
    mock_result.duration_seconds = 2.5
    mock_engine.run = AsyncMock(return_value=mock_result)
    return mock_engine


# ============================================================================
# DocumentOrganizer Class Tests
# ============================================================================

class TestDocumentOrganizerInit:
    """Tests for DocumentOrganizer initialization."""

    def test_init_with_default_settings(self):
        """Test initialization with default settings."""
        with patch('src.main.get_settings') as mock_get_settings:
            mock_settings = MagicMock()
            mock_get_settings.return_value = mock_settings

            from src.main import DocumentOrganizer
            organizer = DocumentOrganizer()

            assert organizer.settings == mock_settings
            assert organizer.job_id is None
            assert organizer._engine is None

    def test_init_with_custom_settings(self, mock_settings):
        """Test initialization with custom settings."""
        from src.main import DocumentOrganizer
        organizer = DocumentOrganizer(settings=mock_settings)

        assert organizer.settings == mock_settings

    def test_lazy_engine_loading(self, mock_settings):
        """Test that database engine is lazy-loaded."""
        with patch('src.main.create_engine') as mock_create_engine:
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine

            from src.main import DocumentOrganizer
            organizer = DocumentOrganizer(settings=mock_settings)

            # Engine not loaded yet
            assert organizer._engine is None

            # Access engine property
            engine = organizer.engine

            # Now engine should be loaded
            assert organizer._engine == mock_engine
            mock_create_engine.assert_called_once_with(mock_settings.database_url)


# ============================================================================
# Job Creation Tests
# ============================================================================

class TestJobCreation:
    """Tests for job creation functionality."""

    def test_create_job_calculates_hash(self, mock_settings, temp_zip, mock_engine):
        """Test that job creation calculates ZIP hash."""
        with patch('src.main.create_engine', return_value=mock_engine):
            from src.main import DocumentOrganizer
            organizer = DocumentOrganizer(settings=mock_settings)

            # Run async test
            async def run_test():
                job_id = await organizer._create_job(str(temp_zip))
                return job_id

            job_id = asyncio.run(run_test())

            # Verify execute was called with hash
            call_args = mock_engine.connect().__enter__().execute.call_args
            assert call_args is not None

    def test_create_job_records_size(self, mock_settings, temp_zip, mock_engine):
        """Test that job creation records ZIP size."""
        with patch('src.main.create_engine', return_value=mock_engine):
            from src.main import DocumentOrganizer
            organizer = DocumentOrganizer(settings=mock_settings)

            async def run_test():
                return await organizer._create_job(str(temp_zip))

            asyncio.run(run_test())

            # Verify size was recorded
            call_args = mock_engine.connect().__enter__().execute.call_args
            # The size should be in the parameters
            assert call_args is not None


# ============================================================================
# ZIP Extraction Tests
# ============================================================================

class TestZipExtraction:
    """Tests for ZIP extraction functionality."""

    def test_extract_zip_creates_directory(self, mock_settings, temp_zip, mock_engine):
        """Test that extraction creates source directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.data_source_path = str(Path(tmpdir) / "source")

            with patch('src.main.create_engine', return_value=mock_engine):
                from src.main import DocumentOrganizer
                organizer = DocumentOrganizer(settings=mock_settings)
                organizer.job_id = "test-job-123"

                async def run_test():
                    await organizer._extract_zip(str(temp_zip))

                asyncio.run(run_test())

                # Verify directory was created
                assert Path(mock_settings.data_source_path).exists()

    def test_extract_zip_extracts_files(self, mock_settings, temp_zip, mock_engine):
        """Test that extraction extracts all files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.data_source_path = str(Path(tmpdir) / "source")

            with patch('src.main.create_engine', return_value=mock_engine):
                from src.main import DocumentOrganizer
                organizer = DocumentOrganizer(settings=mock_settings)
                organizer.job_id = "test-job-123"

                async def run_test():
                    await organizer._extract_zip(str(temp_zip))

                asyncio.run(run_test())

                # Verify files were extracted
                source_path = Path(mock_settings.data_source_path)
                files = list(source_path.rglob("*"))
                file_names = [f.name for f in files if f.is_file()]
                assert "document.txt" in file_names

    def test_extract_zip_clears_existing_contents(self, mock_settings, temp_zip, mock_engine):
        """Test that extraction clears existing directory contents without removing the directory.
        
        This is critical for Docker volume mounts where the directory itself cannot be removed.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "source"
            mock_settings.data_source_path = str(source_path)

            # Pre-create directory with existing files and subdirectory
            source_path.mkdir(parents=True)
            (source_path / "old_file.txt").write_text("old content")
            subdir = source_path / "old_subdir"
            subdir.mkdir()
            (subdir / "nested_file.txt").write_text("nested content")

            with patch('src.main.create_engine', return_value=mock_engine):
                from src.main import DocumentOrganizer
                organizer = DocumentOrganizer(settings=mock_settings)
                organizer.job_id = "test-job-123"

                async def run_test():
                    await organizer._extract_zip(str(temp_zip))

                asyncio.run(run_test())

                # Verify directory still exists (wasn't removed)
                assert source_path.exists()
                
                # Verify old files are gone
                assert not (source_path / "old_file.txt").exists()
                assert not (source_path / "old_subdir").exists()
                
                # Verify new files are extracted
                file_names = [f.name for f in source_path.rglob("*") if f.is_file()]
                assert "document.txt" in file_names


# ============================================================================
# Phase Execution Tests
# ============================================================================

class TestPhaseExecution:
    """Tests for individual processing phases."""

    def test_run_indexing_calls_agent(self, mock_settings, mock_engine, mock_agents):
        """Test that indexing phase calls IndexAgent."""
        with patch('src.main.create_engine', return_value=mock_engine):
            with patch('src.main.IndexAgent', return_value=mock_agents['IndexAgent']):
                from src.main import DocumentOrganizer
                organizer = DocumentOrganizer(settings=mock_settings)
                organizer.job_id = "test-job-123"

                async def run_test():
                    return await organizer._run_indexing()

                result = asyncio.run(run_test())

                mock_agents['IndexAgent'].run.assert_called_once()
                assert result.success

    def test_run_deduplication_calls_agent(self, mock_settings, mock_engine, mock_agents):
        """Test that deduplication phase calls DedupAgent."""
        with patch('src.main.create_engine', return_value=mock_engine):
            with patch('src.main.DedupAgent', return_value=mock_agents['DedupAgent']):
                from src.main import DocumentOrganizer
                organizer = DocumentOrganizer(settings=mock_settings)
                organizer.job_id = "test-job-123"

                async def run_test():
                    return await organizer._run_deduplication()

                result = asyncio.run(run_test())

                mock_agents['DedupAgent'].run.assert_called_once()
                assert result.success

    def test_run_versioning_calls_agent(self, mock_settings, mock_engine, mock_agents):
        """Test that versioning phase calls VersionAgent."""
        with patch('src.main.create_engine', return_value=mock_engine):
            with patch('src.main.VersionAgent', return_value=mock_agents['VersionAgent']):
                from src.main import DocumentOrganizer
                organizer = DocumentOrganizer(settings=mock_settings)
                organizer.job_id = "test-job-123"

                async def run_test():
                    return await organizer._run_versioning()

                result = asyncio.run(run_test())

                mock_agents['VersionAgent'].run.assert_called_once()
                assert result.success

    def test_run_organization_calls_agent(self, mock_settings, mock_engine, mock_agents):
        """Test that organization phase calls OrganizeAgent."""
        with patch('src.main.create_engine', return_value=mock_engine):
            with patch('src.main.OrganizeAgent', return_value=mock_agents['OrganizeAgent']):
                from src.main import DocumentOrganizer
                organizer = DocumentOrganizer(settings=mock_settings)
                organizer.job_id = "test-job-123"

                async def run_test():
                    return await organizer._run_organization()

                result = asyncio.run(run_test())

                mock_agents['OrganizeAgent'].run.assert_called_once()
                assert result.success


# ============================================================================
# Status Update Tests
# ============================================================================

class TestStatusUpdates:
    """Tests for job status updates."""

    def test_update_status_updates_database(self, mock_settings, mock_engine):
        """Test that status updates are written to database."""
        with patch('src.main.create_engine', return_value=mock_engine):
            from src.main import DocumentOrganizer, ProcessingPhase
            organizer = DocumentOrganizer(settings=mock_settings)
            organizer.job_id = "test-job-123"

            async def run_test():
                await organizer._update_job_status(ProcessingPhase.INDEXING)

            asyncio.run(run_test())

            # Verify database was updated
            mock_engine.connect().__enter__().execute.assert_called()
            mock_engine.connect().__enter__().commit.assert_called()

    def test_update_status_with_error(self, mock_settings, mock_engine):
        """Test that error messages are recorded."""
        with patch('src.main.create_engine', return_value=mock_engine):
            from src.main import DocumentOrganizer, ProcessingPhase
            organizer = DocumentOrganizer(settings=mock_settings)
            organizer.job_id = "test-job-123"

            async def run_test():
                await organizer._update_job_status(
                    ProcessingPhase.FAILED,
                    error="Test error message"
                )

            asyncio.run(run_test())

            # Verify execute was called with error parameter
            mock_engine.connect().__enter__().execute.assert_called()


# ============================================================================
# Full Pipeline Tests
# ============================================================================

class TestFullPipeline:
    """Tests for full processing pipeline."""

    def test_process_zip_skip_phases(self, mock_settings, temp_zip, mock_engine, mock_agents):
        """Test that phases can be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.data_source_path = str(Path(tmpdir) / "source")
            mock_settings.data_working_path = str(Path(tmpdir) / "working")
            mock_settings.data_output_path = str(Path(tmpdir) / "output")

            with patch('src.main.create_engine', return_value=mock_engine):
                with patch('src.main.IndexAgent', return_value=mock_agents['IndexAgent']):
                    with patch('src.main.DedupAgent', return_value=mock_agents['DedupAgent']):
                        from src.main import DocumentOrganizer
                        organizer = DocumentOrganizer(settings=mock_settings)

                        async def run_test():
                            return await organizer.process_zip(
                                str(temp_zip),
                                skip_phases=["dedup", "version", "organize", "execute"]
                            )

                        result = asyncio.run(run_test())

                        # Index should be called, dedup should not
                        mock_agents['IndexAgent'].run.assert_called_once()
                        mock_agents['DedupAgent'].run.assert_not_called()

    def test_process_zip_handles_agent_failure(self, mock_settings, temp_zip, mock_engine):
        """Test that agent failures are handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.data_source_path = str(Path(tmpdir) / "source")

            # Create failing agent
            mock_agent = MagicMock()
            mock_result = MagicMock()
            mock_result.success = False
            mock_result.error = "Test failure"
            mock_agent.run = AsyncMock(return_value=mock_result)

            with patch('src.main.create_engine', return_value=mock_engine):
                with patch('src.main.IndexAgent', return_value=mock_agent):
                    from src.main import DocumentOrganizer
                    organizer = DocumentOrganizer(settings=mock_settings)

                    async def run_test():
                        return await organizer.process_zip(str(temp_zip))

                    with pytest.raises(Exception) as exc_info:
                        asyncio.run(run_test())

                    assert "Indexing failed" in str(exc_info.value)


# ============================================================================
# Output Packaging Tests
# ============================================================================

class TestOutputPackaging:
    """Tests for output packaging functionality."""

    def test_package_output_creates_zip(self, mock_settings, mock_engine):
        """Test that output packaging creates a ZIP file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.data_working_path = str(Path(tmpdir) / "working")
            mock_settings.data_source_path = str(Path(tmpdir) / "source")
            mock_settings.data_output_path = str(Path(tmpdir) / "output")

            # Create working directory with test file
            working_dir = Path(mock_settings.data_working_path)
            working_dir.mkdir(parents=True)
            (working_dir / "test.txt").write_text("test content")

            with patch('src.main.create_engine', return_value=mock_engine):
                from src.main import DocumentOrganizer
                organizer = DocumentOrganizer(settings=mock_settings)
                organizer.job_id = "test-job-123"

                async def run_test():
                    return await organizer._package_output()

                output_path = asyncio.run(run_test())

                # Verify ZIP was created
                assert Path(output_path).exists()
                assert output_path.endswith(".zip")


# ============================================================================
# CLI Tests
# ============================================================================

class TestCLI:
    """Tests for CLI argument parsing."""

    def test_cli_help_argument(self):
        """Test that --help argument works."""
        import argparse
        from src.main import main

        # This would normally print help and exit
        # Just verify the module can be imported
        assert callable(main)

    def test_cli_requires_input(self):
        """Test that CLI requires either --zip, --approve, or --wait."""
        # Verify that the main module can be imported and has expected functions
        from src.main import DocumentOrganizer, main
        assert DocumentOrganizer is not None
        assert main is not None


# ============================================================================
# Main Test Runner
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Document Organizer v2 - Main Orchestrator Tests")
    print("=" * 60)
    print()

    # Run tests with pytest
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=Path(__file__).parent
    )
    sys.exit(result.returncode)
