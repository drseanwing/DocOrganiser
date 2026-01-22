#!/usr/bin/env python3
"""
Demo script showing how the VersionAgent detects and processes versions.

This demonstrates the core functionality without requiring database setup.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.agents.version_agent import VersionAgent, VERSION_PATTERNS


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")


def demo_pattern_detection():
    """Demonstrate version pattern detection."""
    print_header("1. VERSION PATTERN DETECTION")
    
    # Create mock agent
    class MockSettings:
        version_archive_strategy = type('obj', (object,), {'value': 'subfolder'})()
        version_folder_name = "_versions"
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    agent = VersionAgent.__new__(VersionAgent)
    agent.settings = MockSettings()
    
    # Test files
    test_files = [
        "Budget_v1.xlsx",
        "Budget_v2.xlsx",
        "Budget_v3_final.xlsx",
        "Report_2024-01-15.pdf",
        "Report_2024-02-20.pdf",
        "Proposal_draft.docx",
        "Proposal_review.docx",
        "Proposal_final.docx",
        "Meeting_Notes (1).txt",
        "Meeting_Notes (2).txt",
        "Plan_rev1.pptx",
        "Plan_rev2.pptx",
    ]
    
    print("Detected version patterns:\n")
    for filename in test_files:
        name_without_ext = Path(filename).stem
        base_name, version_info = agent._extract_version_info(name_without_ext)
        
        if version_info:
            marker = version_info['marker']
            v_type = version_info['type']
            v_value = version_info['value']
            print(f"  ✓ {filename:30} → base: '{base_name}', "
                  f"type: {v_type}, value: {v_value}")
        else:
            print(f"  ✗ {filename:30} → No version marker detected")


def demo_version_grouping():
    """Demonstrate version grouping."""
    print_header("2. VERSION GROUPING")
    
    print("Example 1: Explicit version numbers\n")
    group1 = [
        {"name": "Budget_v1.xlsx", "modified": "2024-01-10", "size": "45 KB"},
        {"name": "Budget_v2.xlsx", "modified": "2024-02-15", "size": "48 KB"},
        {"name": "Budget_v3.xlsx", "modified": "2024-03-20", "size": "52 KB"},
    ]
    
    print("  Files detected as version group:")
    for file in group1:
        print(f"    - {file['name']:20} | Modified: {file['modified']} | Size: {file['size']}")
    
    print("\n  Group properties:")
    print(f"    Base name: 'Budget'")
    print(f"    Extension: 'xlsx'")
    print(f"    Detection method: explicit_marker")
    print(f"    Confidence: 0.95")
    
    print("\n" + "-" * 70)
    print("\nExample 2: Date-based versions\n")
    group2 = [
        {"name": "Report_2024-01-15.pdf", "modified": "2024-01-15", "size": "1.2 MB"},
        {"name": "Report_2024-02-20.pdf", "modified": "2024-02-20", "size": "1.5 MB"},
        {"name": "Report_2024-03-10.pdf", "modified": "2024-03-10", "size": "1.8 MB"},
    ]
    
    print("  Files detected as version group:")
    for file in group2:
        print(f"    - {file['name']:25} | Modified: {file['modified']} | Size: {file['size']}")
    
    print("\n  Group properties:")
    print(f"    Base name: 'Report'")
    print(f"    Extension: 'pdf'")
    print(f"    Detection method: explicit_marker (date)")
    print(f"    Confidence: 0.95")


def demo_version_sorting():
    """Demonstrate version sorting."""
    print_header("3. VERSION SORTING")
    
    class MockSettings:
        version_archive_strategy = type('obj', (object,), {'value': 'subfolder'})()
        version_folder_name = "_versions"
        log_file = None
        log_level = "INFO"
        database_url = "postgresql://localhost/test"
    
    agent = VersionAgent.__new__(VersionAgent)
    agent.settings = MockSettings()
    
    print("Example: Status-based versions (unsorted)\n")
    files = [
        {
            'id': 3,
            'current_name': 'Proposal_final.docx',
            'version_info': {'type': 'status', 'value': 'final', 'marker': '_final'},
            'source_modified_at': datetime(2024, 3, 1)
        },
        {
            'id': 1,
            'current_name': 'Proposal_draft.docx',
            'version_info': {'type': 'status', 'value': 'draft', 'marker': '_draft'},
            'source_modified_at': datetime(2024, 1, 15)
        },
        {
            'id': 2,
            'current_name': 'Proposal_review.docx',
            'version_info': {'type': 'status', 'value': 'review', 'marker': '_review'},
            'source_modified_at': datetime(2024, 2, 10)
        },
    ]
    
    print("  Before sorting:")
    for file in files:
        print(f"    {file['id']}. {file['current_name']:25} | Status: {file['version_info']['value']}")
    
    sorted_files = agent._sort_by_version(files)
    
    print("\n  After sorting (oldest → newest):")
    for idx, file in enumerate(sorted_files, 1):
        print(f"    {idx}. {file['current_name']:25} | Status: {file['version_info']['value']}")
    
    print("\n  Sort priority: draft < review < final")


def demo_archive_structure():
    """Demonstrate archive structure."""
    print_header("4. ARCHIVE STRUCTURE")
    
    print("Strategy 1: SUBFOLDER (default)\n")
    print("  /Documents/Finance/")
    print("    ├── Budget.xlsx                           # Current version")
    print("    └── _versions/Budget/")
    print("        ├── Budget_v1_2024-01-10.xlsx        # Superseded")
    print("        └── Budget_v2_2024-02-15.xlsx        # Superseded")
    
    print("\n" + "-" * 70)
    print("\nStrategy 2: INLINE\n")
    print("  /Documents/Finance/")
    print("    ├── Budget.xlsx                           # Current version")
    print("    ├── Budget_v1_2024-01-10.xlsx            # Superseded (inline)")
    print("    └── Budget_v2_2024-02-15.xlsx            # Superseded (inline)")
    
    print("\n" + "-" * 70)
    print("\nStrategy 3: SEPARATE_ARCHIVE\n")
    print("  /Documents/Finance/")
    print("    └── Budget.xlsx                           # Current version")
    print("")
    print("  /Archive/Versions/Budget/")
    print("    ├── Budget_v1_2024-01-10.xlsx            # Superseded")
    print("    └── Budget_v2_2024-02-15.xlsx            # Superseded")


def demo_database_records():
    """Show what gets written to the database."""
    print_header("5. DATABASE RECORDS")
    
    print("version_chains table:\n")
    print("  id | chain_name | base_path           | current_version | archive_strategy")
    print("  ---|------------|---------------------|-----------------|------------------")
    print("  1  | Budget     | /Documents/Finance  | 3 (v3)          | subfolder")
    print("  2  | Report     | /Documents/Legal    | 3 (2024-03-10)  | subfolder")
    
    print("\n" + "-" * 70)
    print("\nversion_chain_members table:\n")
    print("  chain_id | document_id | version_num | is_current | status      | proposed_name")
    print("  ---------|-------------|-------------|------------|-------------|------------------------")
    print("  1        | 101         | 1           | false      | superseded  | Budget_v1_2024-01-10.xlsx")
    print("  1        | 102         | 2           | false      | superseded  | Budget_v2_2024-02-15.xlsx")
    print("  1        | 103         | 3           | true       | active      | Budget.xlsx")


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "VERSION AGENT - FUNCTIONALITY DEMO" + " " * 19 + "║")
    print("╚" + "=" * 68 + "╝")
    
    demo_pattern_detection()
    demo_version_grouping()
    demo_version_sorting()
    demo_archive_structure()
    demo_database_records()
    
    print("\n" + "=" * 70)
    print("  Demo Complete!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
