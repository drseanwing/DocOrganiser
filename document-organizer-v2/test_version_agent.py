"""
Basic validation tests for VersionAgent.

Tests key functionality without requiring database setup.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.version_agent import VersionAgent, VERSION_PATTERNS


def test_version_patterns():
    """Test that version patterns are defined correctly."""
    print("Testing VERSION_PATTERNS...")
    assert len(VERSION_PATTERNS) > 0, "VERSION_PATTERNS should not be empty"
    print(f"✓ Found {len(VERSION_PATTERNS)} version patterns")


def test_extract_version_info():
    """Test version info extraction from filenames."""
    print("\nTesting _extract_version_info...")
    
    # Create a minimal VersionAgent instance (without DB connection)
    class MockSettings:
        version_archive_strategy = type('obj', (object,), {'value': 'subfolder'})()
        version_folder_name = "_versions"
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    agent = VersionAgent.__new__(VersionAgent)
    agent.settings = MockSettings()
    
    # Test cases
    test_cases = [
        ("Budget_v2", "Budget", "version_number", "2"),
        ("Report_2024-01-15", "Report", "date", "2024-01-15"),
        ("Proposal_draft", "Proposal", "status", "draft"),
        ("Meeting_Notes_rev3", "Meeting_Notes", "revision_number", "3"),
        ("Plan (2)", "Plan", "copy_number", "2"),
        ("Document_20240115", "Document", "date_compact", "20240115"),
        ("NoVersionMarker", "NoVersionMarker", None, None),
    ]
    
    for filename, expected_base, expected_type, expected_value in test_cases:
        base_name, version_info = agent._extract_version_info(filename)
        print(f"  '{filename}' -> base='{base_name}', info={version_info}")
        
        assert base_name == expected_base, f"Expected base '{expected_base}', got '{base_name}'"
        
        if expected_type is None:
            assert version_info is None, f"Expected no version info for '{filename}'"
        else:
            assert version_info is not None, f"Expected version info for '{filename}'"
            assert version_info['type'] == expected_type, \
                f"Expected type '{expected_type}', got '{version_info['type']}'"
            assert version_info['value'] == expected_value, \
                f"Expected value '{expected_value}', got '{version_info['value']}'"
    
    print("✓ All version extraction tests passed")


def test_extract_common_name():
    """Test common name extraction."""
    print("\nTesting _extract_common_name...")
    
    class MockSettings:
        version_archive_strategy = type('obj', (object,), {'value': 'subfolder'})()
        version_folder_name = "_versions"
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    agent = VersionAgent.__new__(VersionAgent)
    agent.settings = MockSettings()
    
    test_cases = [
        (["Budget_v1", "Budget_v2", "Budget_v3"], "Budget"),
        (["Report", "Report (revised)", "Report (final)"], "Report"),
        (["Meeting Notes", "Meeting Notes_draft"], "Meeting Notes"),
        (["Plan_2024-01-01", "Plan_2024-02-01"], "Plan"),
    ]
    
    for names, expected in test_cases:
        result = agent._extract_common_name(names)
        print(f"  {names} -> '{result}'")
        assert result.lower().startswith(expected.lower()[:3]), \
            f"Expected common name to start with '{expected}', got '{result}'"
    
    print("✓ All common name extraction tests passed")


def test_sort_by_version():
    """Test version sorting logic."""
    print("\nTesting _sort_by_version...")
    
    from datetime import datetime
    
    class MockSettings:
        version_archive_strategy = type('obj', (object,), {'value': 'subfolder'})()
        version_folder_name = "_versions"
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    agent = VersionAgent.__new__(VersionAgent)
    agent.settings = MockSettings()
    
    # Create test files with version info
    files = [
        {
            'id': 3,
            'current_name': 'Budget_v3.xlsx',
            'version_info': {'type': 'version_number', 'value': '3'},
            'source_modified_at': datetime(2024, 1, 15)
        },
        {
            'id': 1,
            'current_name': 'Budget_v1.xlsx',
            'version_info': {'type': 'version_number', 'value': '1'},
            'source_modified_at': datetime(2024, 1, 10)
        },
        {
            'id': 2,
            'current_name': 'Budget_v2.xlsx',
            'version_info': {'type': 'version_number', 'value': '2'},
            'source_modified_at': datetime(2024, 1, 12)
        },
    ]
    
    sorted_files = agent._sort_by_version(files)
    ids = [f['id'] for f in sorted_files]
    print(f"  Sorted IDs: {ids}")
    
    assert ids == [1, 2, 3], f"Expected [1, 2, 3], got {ids}"
    print("✓ Version number sorting works correctly")
    
    # Test with status markers
    files_status = [
        {
            'id': 3,
            'current_name': 'Report_final.pdf',
            'version_info': {'type': 'status', 'value': 'final'},
            'source_modified_at': datetime(2024, 1, 15)
        },
        {
            'id': 1,
            'current_name': 'Report_draft.pdf',
            'version_info': {'type': 'status', 'value': 'draft'},
            'source_modified_at': datetime(2024, 1, 10)
        },
        {
            'id': 2,
            'current_name': 'Report_review.pdf',
            'version_info': {'type': 'status', 'value': 'review'},
            'source_modified_at': datetime(2024, 1, 12)
        },
    ]
    
    sorted_files_status = agent._sort_by_version(files_status)
    ids_status = [f['id'] for f in sorted_files_status]
    print(f"  Sorted status IDs: {ids_status}")
    
    assert ids_status == [1, 2, 3], f"Expected [1, 2, 3], got {ids_status}"
    print("✓ Status sorting works correctly")
    
    print("✓ All sorting tests passed")


def main():
    """Run all tests."""
    print("=" * 60)
    print("VersionAgent Validation Tests")
    print("=" * 60)
    
    try:
        test_version_patterns()
        test_extract_version_info()
        test_extract_common_name()
        test_sort_by_version()
        
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
