"""
Basic validation tests for OrganizeAgent and ClaudeService.

Tests key functionality without requiring database or API setup.
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_claude_service_json_extraction():
    """Test JSON extraction from various response formats."""
    print("Testing ClaudeService JSON extraction...")
    
    from src.services.claude_service import ClaudeService
    
    # Create a minimal ClaudeService instance
    class MockSettings:
        anthropic_api_key = None
        claude_model = "claude-sonnet-4-20250514"
        claude_max_tokens = 16000
    
    service = ClaudeService(MockSettings())
    
    # Test case 1: Direct JSON
    direct_json = '{"key": "value", "number": 123}'
    result = service._extract_json(direct_json)
    assert result == {"key": "value", "number": 123}, f"Expected dict, got {result}"
    print("  ✓ Direct JSON extraction works")
    
    # Test case 2: JSON in markdown code block
    markdown_json = '''Here is the response:

```json
{
    "naming_schemas": [],
    "tag_taxonomy": {},
    "directory_structure": [],
    "file_assignments": []
}
```
'''
    result = service._extract_json(markdown_json)
    assert result is not None, "Expected dict, got None"
    assert "naming_schemas" in result, "Missing naming_schemas field"
    print("  ✓ Markdown code block JSON extraction works")
    
    # Test case 3: JSON in generic code block
    generic_block = '''```
{"test": true}
```'''
    result = service._extract_json(generic_block)
    assert result == {"test": True}, f"Expected dict, got {result}"
    print("  ✓ Generic code block JSON extraction works")
    
    # Test case 4: JSON object embedded in text
    embedded_json = 'Some text before {"embedded": "json"} and text after'
    result = service._extract_json(embedded_json)
    assert result == {"embedded": "json"}, f"Expected dict, got {result}"
    print("  ✓ Embedded JSON extraction works")
    
    print("✓ All JSON extraction tests passed")


def test_claude_service_configuration():
    """Test ClaudeService configuration handling."""
    print("\nTesting ClaudeService configuration...")
    
    from src.services.claude_service import ClaudeService
    
    # Test with no API key
    class NoKeySettings:
        anthropic_api_key = None
        claude_model = "claude-sonnet-4-20250514"
        claude_max_tokens = 16000
    
    service = ClaudeService(NoKeySettings())
    assert not service.is_configured(), "Should not be configured without API key"
    print("  ✓ Correctly identifies unconfigured state")
    
    # Test with API key
    class WithKeySettings:
        anthropic_api_key = "test-key"
        claude_model = "claude-sonnet-4-20250514"
        claude_max_tokens = 16000
    
    service = ClaudeService(WithKeySettings())
    assert service.is_configured(), "Should be configured with API key"
    print("  ✓ Correctly identifies configured state")
    
    print("✓ All configuration tests passed")


def test_organize_agent_prompt_building():
    """Test prompt building logic."""
    print("\nTesting OrganizeAgent prompt building...")
    
    from src.agents.organize_agent import OrganizeAgent
    
    # Create a minimal OrganizeAgent instance (without DB connection)
    class MockSettings:
        anthropic_api_key = "test-key"
        claude_model = "claude-sonnet-4-20250514"
        claude_max_tokens = 16000
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    agent = OrganizeAgent.__new__(OrganizeAgent)
    agent.settings = MockSettings()
    
    # Test files
    test_files = [
        {
            "id": 1,
            "current_name": "budget_2024.xlsx",
            "current_path": "/Documents/Finance/budget_2024.xlsx",
            "extension": "xlsx",
            "size_bytes": 45000,
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content_summary": "Q1 2024 budget breakdown by department with forecasts",
            "document_type": "spreadsheet",
            "key_topics": ["budget", "finance", "Q1"],
            "modified_at": "2024-01-15T10:30:00Z",
            "is_version_current": True,
            "version_chain_name": None
        },
        {
            "id": 2,
            "current_name": "meeting_notes.docx",
            "current_path": "/Documents/Meetings/meeting_notes.docx",
            "extension": "docx",
            "size_bytes": 12000,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "content_summary": "Weekly team meeting notes from January 2024",
            "document_type": "document",
            "key_topics": ["meetings", "team"],
            "modified_at": "2024-01-10T09:00:00Z",
            "is_version_current": None,
            "version_chain_name": None
        }
    ]
    
    current_dirs = ["/Documents", "/Documents/Finance", "/Documents/Meetings"]
    
    prompt = agent._build_organization_prompt(test_files, current_dirs)
    
    # Verify prompt contains expected elements
    assert "2 files" in prompt, "Should mention file count"
    assert "budget_2024.xlsx" in prompt, "Should include file name"
    assert "xlsx" in prompt, "Should include file extension"
    assert "/Documents" in prompt, "Should include directory structure"
    print("  ✓ Prompt contains file inventory")
    print("  ✓ Prompt contains directory structure")
    print("  ✓ Prompt contains file type distribution")
    
    # Verify prompt length is reasonable
    assert len(prompt) < 100000, "Prompt should not be too long"
    print(f"  ✓ Prompt length is reasonable ({len(prompt)} chars)")
    
    print("✓ All prompt building tests passed")


def test_organize_agent_parse_plan():
    """Test organization plan parsing logic."""
    print("\nTesting OrganizeAgent plan parsing...")
    
    import asyncio
    from src.agents.organize_agent import OrganizeAgent
    from src.services.claude_service import ClaudeService
    
    # Create a minimal OrganizeAgent instance
    class MockSettings:
        anthropic_api_key = "test-key"
        claude_model = "claude-sonnet-4-20250514"
        claude_max_tokens = 16000
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    agent = OrganizeAgent.__new__(OrganizeAgent)
    agent.settings = MockSettings()
    agent.claude_service = ClaudeService(MockSettings())
    agent.logger = type('obj', (object,), {
        'warning': lambda *a, **k: None,
        'error': lambda *a, **k: None,
        'info': lambda *a, **k: None
    })()
    
    # Test files
    test_files = [
        {"id": 1, "current_name": "file1.docx"},
        {"id": 2, "current_name": "file2.xlsx"},
        {"id": 3, "current_name": "file3.pdf"}
    ]
    
    # Valid response with all files assigned
    valid_response = json.dumps({
        "naming_schemas": [
            {
                "document_type": "document",
                "pattern": "{date}_{title}",
                "example": "2024-01-15_Report.docx",
                "description": "Standard document naming",
                "placeholders": {"date": "YYYY-MM-DD", "title": "Document title"}
            }
        ],
        "tag_taxonomy": {
            "documents": {
                "description": "Document files",
                "children": {
                    "reports": {"description": "Report files"}
                }
            }
        },
        "directory_structure": [
            {"path": "/Documents", "purpose": "All documents", "expected_types": ["docx", "pdf"]},
            {"path": "/Spreadsheets", "purpose": "Spreadsheet files", "expected_types": ["xlsx"]}
        ],
        "file_assignments": [
            {"file_id": 1, "proposed_name": "2024-01-15_file1.docx", "proposed_path": "/Documents", "proposed_tags": ["documents"], "reasoning": "Standard document"},
            {"file_id": 2, "proposed_name": None, "proposed_path": "/Spreadsheets", "proposed_tags": ["spreadsheets"], "reasoning": "Keep original name"},
            {"file_id": 3, "proposed_name": None, "proposed_path": None, "proposed_tags": ["uncategorized"], "reasoning": "Could not categorize"}
        ]
    })
    
    async def run_parse():
        return await agent._parse_organization_plan(valid_response, test_files)
    
    result = asyncio.run(run_parse())
    
    assert result is not None, "Should parse valid response"
    assert len(result["naming_schemas"]) == 1, "Should have 1 naming schema"
    assert len(result["file_assignments"]) == 3, "Should have 3 file assignments"
    print("  ✓ Valid response parsing works")
    
    # Test response with missing file assignments
    partial_response = json.dumps({
        "naming_schemas": [],
        "tag_taxonomy": {},
        "directory_structure": [],
        "file_assignments": [
            {"file_id": 1, "proposed_name": None, "proposed_path": None, "proposed_tags": [], "reasoning": ""}
        ]
    })
    
    async def run_partial_parse():
        return await agent._parse_organization_plan(partial_response, test_files)
    
    result = asyncio.run(run_partial_parse())
    
    assert result is not None, "Should parse partial response"
    assert len(result["file_assignments"]) == 3, "Should auto-fill missing assignments"
    print("  ✓ Auto-fills missing file assignments")
    
    print("✓ All plan parsing tests passed")


def test_organize_agent_directory_extraction():
    """Test directory extraction from file paths."""
    print("\nTesting OrganizeAgent directory extraction...")
    
    import asyncio
    from src.agents.organize_agent import OrganizeAgent
    
    # Create a minimal OrganizeAgent instance
    class MockSettings:
        anthropic_api_key = "test-key"
        claude_model = "claude-sonnet-4-20250514"
        claude_max_tokens = 16000
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    agent = OrganizeAgent.__new__(OrganizeAgent)
    agent.settings = MockSettings()
    
    test_files = [
        {"current_path": "/Documents/Finance/Reports/Q1/budget.xlsx"},
        {"current_path": "/Documents/Finance/Invoices/invoice.pdf"},
        {"current_path": "/Media/Images/photo.jpg"}
    ]
    
    async def run_get_dirs():
        return await agent._get_current_directories(test_files)
    
    dirs = asyncio.run(run_get_dirs())
    
    # Should include all parent directories
    assert "/Documents" in dirs, "Should include /Documents"
    assert "/Documents/Finance" in dirs, "Should include /Documents/Finance"
    assert "/Documents/Finance/Reports" in dirs, "Should include /Documents/Finance/Reports"
    assert "/Documents/Finance/Reports/Q1" in dirs, "Should include /Documents/Finance/Reports/Q1"
    assert "/Media" in dirs, "Should include /Media"
    assert "/Media/Images" in dirs, "Should include /Media/Images"
    print(f"  ✓ Extracted {len(dirs)} directories from file paths")
    
    print("✓ All directory extraction tests passed")


def main():
    """Run all tests."""
    print("=" * 60)
    print("OrganizeAgent and ClaudeService Validation Tests")
    print("=" * 60)
    
    try:
        test_claude_service_json_extraction()
        test_claude_service_configuration()
        test_organize_agent_prompt_building()
        test_organize_agent_parse_plan()
        test_organize_agent_directory_extraction()
        
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
