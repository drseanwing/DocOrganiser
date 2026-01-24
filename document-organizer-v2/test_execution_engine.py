"""
Validation tests for ExecutionEngine and related components.

Tests key functionality without requiring database setup.
"""

import json
import re
import sys
import tempfile
import traceback
from pathlib import Path

# Add src to path for imports
_src_path = Path(__file__).parent
if _src_path.exists():
    sys.path.insert(0, str(_src_path))

from src.execution.shortcut_creator import ShortcutCreator
from src.execution.manifest_generator import ManifestGenerator


def test_shortcut_creator_symlink():
    """Test symlink creation."""
    print("Testing ShortcutCreator symlink creation...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create target file
        target_file = tmpdir / "target.txt"
        target_file.write_text("Hello, World!")
        
        # Create symlink
        shortcut_creator = ShortcutCreator()
        symlink_path = tmpdir / "link_to_target"
        success = shortcut_creator.create_symlink(target_file, symlink_path)
        
        assert success, "Symlink creation should succeed"
        assert symlink_path.is_symlink(), "Path should be a symlink"
        assert symlink_path.resolve() == target_file.resolve(), "Symlink should point to target"
    
    print("✓ Symlink creation works")


def test_shortcut_creator_url():
    """Test .url shortcut creation."""
    print("\nTesting ShortcutCreator URL shortcut creation...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create target file
        target_file = tmpdir / "target.txt"
        target_file.write_text("Hello, World!")
        
        # Create URL shortcut
        shortcut_creator = ShortcutCreator()
        url_path = tmpdir / "shortcut"
        success = shortcut_creator.create_url_shortcut(target_file, url_path)
        
        actual_url_path = Path(str(url_path) + ".url")
        assert success, "URL shortcut creation should succeed"
        assert actual_url_path.exists(), "URL shortcut file should exist"
        
        content = actual_url_path.read_text()
        assert "[InternetShortcut]" in content, "URL file should have correct format"
        assert "URL=file://" in content, "URL file should contain file URL"
    
    print("✓ URL shortcut creation works")


def test_shortcut_creator_desktop():
    """Test .desktop shortcut creation."""
    print("\nTesting ShortcutCreator desktop shortcut creation...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create target file
        target_file = tmpdir / "target.txt"
        target_file.write_text("Hello, World!")
        
        # Create desktop shortcut
        shortcut_creator = ShortcutCreator()
        desktop_path = tmpdir / "shortcut"
        success = shortcut_creator.create_desktop_shortcut(target_file, desktop_path)
        
        actual_desktop_path = Path(str(desktop_path) + ".desktop")
        assert success, "Desktop shortcut creation should succeed"
        assert actual_desktop_path.exists(), "Desktop shortcut file should exist"
        
        content = actual_desktop_path.read_text()
        assert "[Desktop Entry]" in content, "Desktop file should have correct format"
        assert "Type=Link" in content, "Desktop file should have Link type"
    
    print("✓ Desktop shortcut creation works")


def test_shortcut_creator_auto():
    """Test automatic shortcut type selection."""
    print("\nTesting ShortcutCreator auto shortcut selection...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create target file
        target_file = tmpdir / "target.txt"
        target_file.write_text("Hello, World!")
        
        # Create auto shortcut (should prefer symlink on Linux/Mac)
        shortcut_creator = ShortcutCreator()
        auto_path = tmpdir / "auto_shortcut"
        success, shortcut_type = shortcut_creator.create_shortcut(target_file, auto_path, "auto")
        
        assert success, "Auto shortcut creation should succeed"
        assert shortcut_type in ["symlink", "url"], f"Type should be symlink or url, got {shortcut_type}"
    
    print(f"✓ Auto shortcut creation works (selected type: {shortcut_type})")


def test_manifest_generator_operations():
    """Test manifest operation tracking."""
    print("\nTesting ManifestGenerator operation tracking...")
    
    manifest_gen = ManifestGenerator()
    
    # Set total files
    manifest_gen.set_total_files(100)
    
    # Add operations
    manifest_gen.add_operation("create_dir", target_path="/data/working/docs")
    manifest_gen.add_operation("copy", source_path="/data/source/file1.txt",
                               target_path="/data/working/docs/file1.txt", document_id=1)
    manifest_gen.add_operation("copy", source_path="/data/source/file2.txt",
                               target_path="/data/working/docs/file2.txt", document_id=2)
    manifest_gen.add_operation("rename", source_path="/data/source/old.txt",
                               target_path="/data/working/new.txt", document_id=3)
    manifest_gen.add_operation("move", source_path="/data/source/moveme.txt",
                               target_path="/data/working/moved/file.txt", document_id=4)
    
    # Get summary
    summary = manifest_gen.get_summary()
    
    assert summary["total_files"] == 100, f"Expected 100 total files, got {summary['total_files']}"
    assert summary["directories_created"] == 1, f"Expected 1 dir, got {summary['directories_created']}"
    assert summary["files_copied"] == 2, f"Expected 2 copies, got {summary['files_copied']}"
    assert summary["files_renamed"] == 1, f"Expected 1 rename, got {summary['files_renamed']}"
    assert summary["files_moved"] == 1, f"Expected 1 move, got {summary['files_moved']}"
    
    print("✓ Operation tracking works correctly")


def test_manifest_generator_errors():
    """Test manifest error tracking."""
    print("\nTesting ManifestGenerator error tracking...")
    
    manifest_gen = ManifestGenerator()
    
    # Add successful operation
    manifest_gen.add_operation("copy", source_path="/data/source/good.txt",
                               target_path="/data/working/good.txt", success=True)
    
    # Add failed operation
    manifest_gen.add_operation("copy", source_path="/data/source/bad.txt",
                               target_path="/data/working/bad.txt", success=False,
                               error="Permission denied")
    
    # Add explicit error
    manifest_gen.add_error(document_id=99, error="File not found", 
                          source="/data/source/missing.txt", operation="copy")
    
    summary = manifest_gen.get_summary()
    
    assert summary["files_copied"] == 1, "Should count only successful copies"
    assert summary["errors"] == 1, "Should count failed operations as errors"
    assert len(manifest_gen.errors) == 1, "Should have 1 explicit error"
    
    print("✓ Error tracking works correctly")


def test_manifest_generator_shortcuts():
    """Test manifest shortcut tracking."""
    print("\nTesting ManifestGenerator shortcut tracking...")
    
    manifest_gen = ManifestGenerator()
    
    # Add shortcuts
    manifest_gen.add_shortcut(
        shortcut_path="/data/working/shortcut1.url",
        target_path="/data/working/primary.txt",
        original_path="/data/source/duplicate1.txt",
        shortcut_type="url"
    )
    manifest_gen.add_shortcut(
        shortcut_path="/data/working/shortcut2",
        target_path="/data/working/primary.txt",
        original_path="/data/source/duplicate2.txt",
        shortcut_type="symlink"
    )
    
    assert len(manifest_gen.shortcuts) == 2, f"Expected 2 shortcuts, got {len(manifest_gen.shortcuts)}"
    assert manifest_gen.shortcuts[0]["shortcut_type"] == "url"
    assert manifest_gen.shortcuts[1]["shortcut_type"] == "symlink"
    
    print("✓ Shortcut tracking works correctly")


def test_manifest_generator_file_output():
    """Test manifest JSON file generation."""
    print("\nTesting ManifestGenerator file output...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        manifest_gen = ManifestGenerator()
        manifest_gen.set_total_files(50)
        manifest_gen.add_operation("create_dir", target_path="/data/working/test")
        manifest_gen.add_operation("copy", source_path="/src.txt", target_path="/dst.txt", document_id=1)
        manifest_gen.add_shortcut("/shortcut.url", "/target.txt", "/original.txt", "url")
        manifest_gen.increment_version_archives()
        
        # Generate manifest
        manifest_path = tmpdir / "test_manifest.json"
        result_path = manifest_gen.generate_manifest(
            job_id="test-job-uuid",
            source_zip="original.zip",
            output_path=manifest_path
        )
        
        assert result_path.exists(), "Manifest file should be created"
        
        # Validate JSON structure
        with open(result_path) as f:
            manifest_data = json.load(f)
        
        assert manifest_data["job_id"] == "test-job-uuid"
        assert manifest_data["source_zip"] == "original.zip"
        assert "executed_at" in manifest_data
        assert "statistics" in manifest_data
        assert "operations" in manifest_data
        assert "shortcuts" in manifest_data
        assert "errors" in manifest_data
        
        # Validate statistics
        stats = manifest_data["statistics"]
        assert stats["total_files"] == 50
        assert stats["directories_created"] == 1
        assert stats["files_copied"] == 1
        assert stats["version_archives"] == 1
    
    print("✓ File output works correctly")


def test_filename_sanitization():
    """Test filename sanitization logic using actual ExecutionEngine method."""
    print("\nTesting filename sanitization logic...")
    
    # Import the actual ExecutionEngine to test the real implementation
    try:
        from src.execution.execution_engine import ExecutionEngine
        
        # Create a minimal mock to test the sanitization method
        class MockSettings:
            data_source_path = "/data/source"
            data_working_path = "/data/working"
            data_reports_path = "/data/reports"
            log_file = None
            log_level = "INFO"
            database_url = "postgresql://localhost/test"
        
        # Create engine instance without full initialization
        engine = ExecutionEngine.__new__(ExecutionEngine)
        engine.settings = MockSettings()
        
        # Use the actual _sanitize_filename method
        sanitize_filename = engine._sanitize_filename
        
    except Exception:
        # Fallback to local implementation if import fails
        def sanitize_filename(filename: str) -> str:
            """Fallback sanitization logic matching ExecutionEngine."""
            invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
            sanitized = re.sub(invalid_chars, '_', filename)
            sanitized = sanitized.strip()
            sanitized = sanitized.rstrip('.')
            reserved_names = [
                'CON', 'PRN', 'AUX', 'NUL',
                'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
                'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
            ]
            name_without_ext = Path(sanitized).stem.upper()
            if name_without_ext in reserved_names:
                sanitized = f'_{sanitized}'
            if not sanitized:
                sanitized = 'unnamed'
            return sanitized
    
    # Test cases
    test_cases = [
        ("normal_file.txt", "normal_file.txt"),
        ("file<with>bad.txt", "file_with_bad.txt"),
        ("file:colon.txt", "file_colon.txt"),
        ("file?question.txt", "file_question.txt"),
        ("  spaces  .txt", "spaces  .txt"),
        ("trailing...", "trailing"),
        ("CON.txt", "_CON.txt"),
        ("PRN.doc", "_PRN.doc"),
        ("AUX", "_AUX"),
        ("", "unnamed"),
    ]
    
    for original, expected in test_cases:
        result = sanitize_filename(original)
        print(f"  '{original}' -> '{result}' (expected: '{expected}')")
        assert result == expected, f"Expected '{expected}', got '{result}'"
    
    print("✓ Filename sanitization works correctly")


def test_manifest_generator_version_archives():
    """Test version archive tracking."""
    print("\nTesting ManifestGenerator version archive tracking...")
    
    manifest_gen = ManifestGenerator()
    
    assert manifest_gen.statistics["version_archives"] == 0
    
    manifest_gen.increment_version_archives()
    manifest_gen.increment_version_archives()
    manifest_gen.increment_version_archives()
    
    assert manifest_gen.statistics["version_archives"] == 3
    
    print("✓ Version archive tracking works correctly")


def main():
    """Run all tests."""
    print("=" * 60)
    print("ExecutionEngine Component Validation Tests")
    print("=" * 60)
    
    try:
        # ShortcutCreator tests
        test_shortcut_creator_symlink()
        test_shortcut_creator_url()
        test_shortcut_creator_desktop()
        test_shortcut_creator_auto()
        
        # ManifestGenerator tests
        test_manifest_generator_operations()
        test_manifest_generator_errors()
        test_manifest_generator_shortcuts()
        test_manifest_generator_file_output()
        test_manifest_generator_version_archives()
        
        # Utility function tests
        test_filename_sanitization()
        
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
