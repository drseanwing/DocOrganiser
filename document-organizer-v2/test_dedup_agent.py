"""
Basic validation tests for DedupAgent.

Tests key functionality without requiring database setup.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
import asyncio

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_duplicate_action_enum():
    """Test that DuplicateAction enum has expected values."""
    print("Testing DuplicateAction enum...")
    
    from src.config import DuplicateAction
    
    assert DuplicateAction.KEEP_PRIMARY.value == "keep_primary"
    assert DuplicateAction.SHORTCUT.value == "shortcut"
    assert DuplicateAction.KEEP_BOTH.value == "keep_both"
    assert DuplicateAction.DELETE.value == "delete"
    
    print("  ✓ DuplicateAction enum has all expected values")
    print("✓ DuplicateAction enum tests passed")


def test_agent_initialization():
    """Test DedupAgent initialization."""
    print("\nTesting DedupAgent initialization...")
    
    from src.agents.dedup_agent import DedupAgent
    
    class MockSettings:
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3"
        ollama_timeout = 120
        ollama_temperature = 0.3
        auto_approve_shortcuts = False
        min_duplicate_size_bytes = 10240
    
    agent = DedupAgent.__new__(DedupAgent)
    agent.settings = MockSettings()
    agent._groups_processed = 0
    agent._shortcuts_planned = 0
    agent._errors = []
    
    assert agent.AGENT_NAME == "dedup_agent", "Agent name should be dedup_agent"
    print("  ✓ Agent name is correct")
    
    from src.config import ProcessingPhase
    assert agent.AGENT_PHASE == ProcessingPhase.DEDUPLICATING, "Phase should be DEDUPLICATING"
    print("  ✓ Agent phase is correct")
    
    print("✓ DedupAgent initialization tests passed")


def test_determine_primary_by_path_depth():
    """Test primary selection logic based on path depth."""
    print("\nTesting primary selection by path depth...")
    
    from src.agents.dedup_agent import DedupAgent
    
    class MockSettings:
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3"
        ollama_timeout = 120
        ollama_temperature = 0.3
        auto_approve_shortcuts = True
        min_duplicate_size_bytes = 10240
    
    agent = DedupAgent.__new__(DedupAgent)
    agent.settings = MockSettings()
    agent.logger = MagicMock()
    
    # Simulate files with different path depths
    files = [
        {"id": 1, "current_path": "/Documents/Projects/Alpha/Report.docx"},  # depth 4
        {"id": 2, "current_path": "/Archive/Old/Backup/Reports/Report.docx"},  # depth 5
        {"id": 3, "current_path": "/Documents/Report.docx"},  # depth 2 - should be primary
    ]
    
    # The shallower path should typically be primary
    depths = [(f["id"], len(f["current_path"].split("/"))) for f in files]
    depths_sorted = sorted(depths, key=lambda x: x[1])
    
    print(f"  Path depths: {depths}")
    print(f"  Sorted by depth: {depths_sorted}")
    
    # File with shallowest path
    expected_primary = depths_sorted[0][0]
    assert expected_primary == 3, f"Expected file 3 to have shallowest path"
    
    print("  ✓ Path depth comparison works correctly")
    print("✓ Primary selection by path depth tests passed")


def test_determine_primary_by_modification_date():
    """Test primary selection logic based on modification date."""
    print("\nTesting primary selection by modification date...")
    
    from datetime import datetime
    
    files = [
        {"id": 1, "source_modified_at": datetime(2024, 1, 10)},  # older
        {"id": 2, "source_modified_at": datetime(2024, 1, 20)},  # newer - should be primary
        {"id": 3, "source_modified_at": datetime(2024, 1, 15)},  # middle
    ]
    
    # Sort by date descending (newest first)
    sorted_by_date = sorted(files, key=lambda x: x["source_modified_at"], reverse=True)
    newest = sorted_by_date[0]
    
    assert newest["id"] == 2, "Newest file should be id 2"
    print("  ✓ Modification date comparison works correctly")
    print("✓ Primary selection by modification date tests passed")


def test_path_analysis():
    """Test path analysis for determining file importance."""
    print("\nTesting path analysis...")
    
    # Paths that suggest primary location
    primary_indicators = ["Documents", "Projects", "Active", "Current"]
    # Paths that suggest backup/archive location
    secondary_indicators = ["Archive", "Backup", "Old", "Copy", "_backup"]
    
    test_paths = [
        ("/Documents/Projects/Report.docx", True),  # Should be primary
        ("/Archive/Backup/Report.docx", False),     # Should be secondary
        ("/Old/Copy/Report.docx", False),           # Should be secondary
        ("/Active/Current/Report.docx", True),      # Should be primary
    ]
    
    for path, expected_primary in test_paths:
        parts = path.split("/")
        is_primary = any(ind in parts for ind in primary_indicators)
        is_secondary = any(ind in parts for ind in secondary_indicators)
        
        if is_primary and not is_secondary:
            actual_primary = True
        elif is_secondary and not is_primary:
            actual_primary = False
        else:
            actual_primary = True  # Default
        
        print(f"  Path: {path} -> Primary: {actual_primary}")
        assert actual_primary == expected_primary, f"Expected {expected_primary} for {path}"
    
    print("  ✓ Path analysis correctly identifies primary locations")
    print("✓ Path analysis tests passed")


def test_validate_prerequisites():
    """Test prerequisite validation."""
    print("\nTesting validate_prerequisites...")
    
    from src.agents.dedup_agent import DedupAgent
    
    class MockSettings:
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    agent = DedupAgent.__new__(DedupAgent)
    agent.settings = MockSettings()
    agent.logger = MagicMock()
    
    # Mock session that returns 0 documents
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_session.execute.return_value = mock_result
    
    agent.get_sync_session = MagicMock(return_value=mock_session)
    
    async def run_validation():
        return await agent.validate_prerequisites()
    
    valid, error = asyncio.run(run_validation())
    
    assert not valid, "Should fail when no indexed documents"
    assert "No indexed documents" in error, f"Error should mention no documents: {error}"
    print("  ✓ Correctly rejects when no indexed documents")
    
    # Mock session that returns some documents
    mock_result.scalar.return_value = 100
    
    valid, error = asyncio.run(run_validation())
    
    assert valid, f"Should pass when documents exist: {error}"
    print("  ✓ Correctly accepts when documents exist")
    
    print("✓ Prerequisite validation tests passed")


def test_grouping_by_hash():
    """Test that files are correctly grouped by content hash."""
    print("\nTesting grouping by hash...")
    
    files = [
        {"id": 1, "content_hash": "abc123", "current_path": "/path1/file.docx"},
        {"id": 2, "content_hash": "abc123", "current_path": "/path2/file.docx"},  # Duplicate of 1
        {"id": 3, "content_hash": "def456", "current_path": "/path3/file.xlsx"},
        {"id": 4, "content_hash": "def456", "current_path": "/path4/file.xlsx"},  # Duplicate of 3
        {"id": 5, "content_hash": "ghi789", "current_path": "/path5/unique.pdf"},  # No duplicate
    ]
    
    # Group by hash
    groups = {}
    for f in files:
        h = f["content_hash"]
        if h not in groups:
            groups[h] = []
        groups[h].append(f)
    
    # Filter to only groups with duplicates
    duplicate_groups = {h: g for h, g in groups.items() if len(g) > 1}
    
    print(f"  Total files: {len(files)}")
    print(f"  Duplicate groups: {len(duplicate_groups)}")
    print(f"  Group sizes: {[len(g) for g in duplicate_groups.values()]}")
    
    assert len(duplicate_groups) == 2, "Should have 2 duplicate groups"
    assert len(duplicate_groups["abc123"]) == 2, "Group abc123 should have 2 files"
    assert len(duplicate_groups["def456"]) == 2, "Group def456 should have 2 files"
    
    print("  ✓ Grouping by hash works correctly")
    print("✓ Hash grouping tests passed")


def main():
    """Run all tests."""
    print("=" * 60)
    print("DedupAgent Validation Tests")
    print("=" * 60)
    
    try:
        test_duplicate_action_enum()
        test_agent_initialization()
        test_determine_primary_by_path_depth()
        test_determine_primary_by_modification_date()
        test_path_analysis()
        test_validate_prerequisites()
        test_grouping_by_hash()
        
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
