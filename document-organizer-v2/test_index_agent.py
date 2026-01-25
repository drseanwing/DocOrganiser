"""
Basic validation tests for IndexAgent.

Tests key functionality without requiring database setup.
"""

import sys
import hashlib
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock
import tempfile
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_walk_files_filters_correctly():
    """Test that file walking respects extension filters."""
    print("Testing _walk_files filtering...")
    
    from src.agents.index_agent import IndexAgent
    
    # Create a minimal IndexAgent instance
    class MockSettings:
        data_source_path = None  # Will be set per test
        supported_extensions = ["docx", "pdf", "xlsx"]
        max_file_size_bytes = 100 * 1024 * 1024  # 100MB
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
        batch_size = 50
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    # Create a temporary directory with test files
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        (Path(tmpdir) / "document.docx").touch()
        (Path(tmpdir) / "report.pdf").touch()
        (Path(tmpdir) / "data.xlsx").touch()
        (Path(tmpdir) / "script.py").touch()  # Should be filtered out
        (Path(tmpdir) / ".hidden").touch()  # Should be filtered out
        (Path(tmpdir) / "~temp.docx").touch()  # Should be filtered out
        
        mock_settings = MockSettings()
        mock_settings.data_source_path = tmpdir
        
        agent = IndexAgent.__new__(IndexAgent)
        agent.settings = mock_settings
        agent.logger = MagicMock()
        
        files = agent._walk_files(Path(tmpdir))
        file_names = [f.name for f in files]
        
        print(f"  Found files: {file_names}")
        
        assert "document.docx" in file_names, "Should include .docx files"
        assert "report.pdf" in file_names, "Should include .pdf files"
        assert "data.xlsx" in file_names, "Should include .xlsx files"
        assert "script.py" not in file_names, "Should exclude .py files (not in supported)"
        assert ".hidden" not in file_names, "Should exclude hidden files"
        assert "~temp.docx" not in file_names, "Should exclude temp files"
        
    print("✓ File walking filters work correctly")


def test_calculate_hash():
    """Test SHA256 hash calculation."""
    print("\nTesting _calculate_hash...")
    
    from src.agents.index_agent import IndexAgent
    
    class MockSettings:
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    agent = IndexAgent.__new__(IndexAgent)
    agent.settings = MockSettings()
    
    # Create a temp file with known content
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Hello, World!")
        temp_path = f.name
    
    try:
        # Calculate expected hash
        expected_hash = hashlib.sha256(b"Hello, World!").hexdigest()
        
        # Calculate using agent method
        actual_hash = agent._calculate_hash(Path(temp_path))
        
        print(f"  Expected: {expected_hash[:16]}...")
        print(f"  Actual:   {actual_hash[:16]}...")
        
        assert actual_hash == expected_hash, f"Hash mismatch: expected {expected_hash}, got {actual_hash}"
        
    finally:
        os.unlink(temp_path)
    
    print("✓ Hash calculation works correctly")


def test_walk_files_size_filter():
    """Test that large files are filtered out."""
    print("\nTesting _walk_files size filtering...")
    
    from src.agents.index_agent import IndexAgent
    
    class MockSettings:
        data_source_path = None
        supported_extensions = ["txt"]
        max_file_size_bytes = 100  # 100 bytes limit for testing
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a small file (should be included)
        small_file = Path(tmpdir) / "small.txt"
        small_file.write_text("small")
        
        # Create a large file (should be filtered)
        large_file = Path(tmpdir) / "large.txt"
        large_file.write_text("x" * 200)  # 200 bytes
        
        mock_settings = MockSettings()
        mock_settings.data_source_path = tmpdir
        
        agent = IndexAgent.__new__(IndexAgent)
        agent.settings = mock_settings
        agent.logger = MagicMock()
        
        files = agent._walk_files(Path(tmpdir))
        file_names = [f.name for f in files]
        
        print(f"  Found files: {file_names}")
        
        assert "small.txt" in file_names, "Should include small files"
        assert "large.txt" not in file_names, "Should exclude large files"
    
    print("✓ Size filtering works correctly")


def test_walk_files_nested_directories():
    """Test that nested directories are walked correctly."""
    print("\nTesting _walk_files with nested directories...")
    
    from src.agents.index_agent import IndexAgent
    
    class MockSettings:
        data_source_path = None
        supported_extensions = ["txt", "docx"]
        max_file_size_bytes = 100 * 1024 * 1024
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create nested structure
        (Path(tmpdir) / "root.txt").touch()
        (Path(tmpdir) / "level1").mkdir()
        (Path(tmpdir) / "level1" / "file1.txt").touch()
        (Path(tmpdir) / "level1" / "level2").mkdir()
        (Path(tmpdir) / "level1" / "level2" / "file2.docx").touch()
        
        mock_settings = MockSettings()
        mock_settings.data_source_path = tmpdir
        
        agent = IndexAgent.__new__(IndexAgent)
        agent.settings = mock_settings
        agent.logger = MagicMock()
        
        files = agent._walk_files(Path(tmpdir))
        file_names = [f.name for f in files]
        
        print(f"  Found files: {file_names}")
        
        assert len(files) == 3, f"Should find 3 files, found {len(files)}"
        assert "root.txt" in file_names, "Should find root level file"
        assert "file1.txt" in file_names, "Should find level1 file"
        assert "file2.docx" in file_names, "Should find level2 file"
    
    print("✓ Nested directory walking works correctly")


def test_validate_prerequisites():
    """Test prerequisite validation."""
    print("\nTesting validate_prerequisites...")
    
    import asyncio
    from src.agents.index_agent import IndexAgent
    
    class MockSettings:
        data_source_path = "/nonexistent/path"
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    agent = IndexAgent.__new__(IndexAgent)
    agent.settings = MockSettings()
    agent.logger = MagicMock()
    agent.ollama_service = MagicMock()
    agent.ollama_service.health_check = AsyncMock(return_value=True)
    
    async def run_validation():
        return await agent.validate_prerequisites()
    
    valid, error = asyncio.run(run_validation())
    
    assert not valid, "Should fail for nonexistent directory"
    assert "does not exist" in error, f"Error should mention directory doesn't exist: {error}"
    print("  ✓ Correctly rejects nonexistent directory")
    
    # Test with valid directory
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create at least one file
        (Path(tmpdir) / "test.txt").touch()
        
        agent.settings.data_source_path = tmpdir
        
        valid, error = asyncio.run(run_validation())
        
        assert valid, f"Should pass for valid directory with files: {error}"
        print("  ✓ Correctly accepts valid directory with files")
    
    print("✓ Prerequisite validation works correctly")


def main():
    """Run all tests."""
    print("=" * 60)
    print("IndexAgent Validation Tests")
    print("=" * 60)
    
    try:
        test_walk_files_filters_correctly()
        test_calculate_hash()
        test_walk_files_size_filter()
        test_walk_files_nested_directories()
        test_validate_prerequisites()
        
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
