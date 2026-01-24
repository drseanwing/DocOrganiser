"""
String Utilities Module.

Provides reusable functions for string manipulation including:
- String similarity calculations
- Version information extraction from filenames
- Filename sanitization and cleaning

Extracted from inline implementations in VersionAgent for reusability.
"""

import re
from typing import Dict, Optional, Tuple, List


# Version detection patterns with their types
VERSION_PATTERNS = [
    (r'_v(\d+)', 'version_number'),           # _v1, _v2
    (r'_rev(\d+)', 'revision_number'),        # _rev1, _rev2  
    (r'_version(\d+)', 'version_number'),     # _version1
    (r'\s*\((\d+)\)', 'copy_number'),         # (1), (2)
    (r'_(\d{4}-\d{2}-\d{2})', 'date'),        # _2024-01-15
    (r'_(\d{8})', 'date_compact'),            # _20240115
    (r'_(draft|final|approved|review|wip)', 'status'),  # _draft, _final
]

# Status priority for version sorting (lower = older)
STATUS_PRIORITY = {
    'draft': 1,
    'wip': 2,
    'review': 3,
    'approved': 4,
    'final': 5
}

# Characters not allowed in filenames
UNSAFE_FILENAME_CHARS = r'[<>:"/\\|?*\x00-\x1f]'


def levenshtein_similarity(s1: str, s2: str) -> float:
    """
    Calculate Levenshtein similarity ratio between two strings.
    
    Uses the python-Levenshtein library for efficient calculation.
    Returns a ratio from 0.0 (completely different) to 1.0 (identical).
    
    Args:
        s1: First string to compare
        s2: Second string to compare
        
    Returns:
        Similarity ratio between 0.0 and 1.0
        
    Example:
        >>> levenshtein_similarity("Budget_v1.xlsx", "Budget_v2.xlsx")
        0.9285714285714286
        >>> levenshtein_similarity("report.pdf", "invoice.pdf")
        0.5
    """
    try:
        from Levenshtein import ratio
        return ratio(s1, s2)
    except ImportError:
        # Fallback to simple implementation if Levenshtein not available
        return _simple_similarity(s1, s2)


def _simple_similarity(s1: str, s2: str) -> float:
    """
    Simple fallback similarity calculation.
    
    Uses longest common subsequence ratio.
    """
    if not s1 or not s2:
        return 0.0
    
    if s1 == s2:
        return 1.0
    
    # Calculate longest common prefix ratio as simple approximation
    common = 0
    for c1, c2 in zip(s1.lower(), s2.lower()):
        if c1 == c2:
            common += 1
        else:
            break
    
    return (2.0 * common) / (len(s1) + len(s2))


def extract_version_info(filename: str) -> Tuple[str, Optional[Dict[str, str]]]:
    """
    Extract version marker information from a filename.
    
    Searches for common version patterns in the filename and returns
    the base name (without version marker) and version information.
    
    Args:
        filename: Filename to analyze (without extension recommended)
        
    Returns:
        Tuple of (base_name, version_info_dict or None)
        - base_name: Filename with version marker removed
        - version_info: Dictionary with 'type', 'value', and 'marker' keys,
                       or None if no version pattern found
        
    Example:
        >>> extract_version_info("Budget_v2")
        ('Budget', {'type': 'version_number', 'value': '2', 'marker': '_v2'})
        
        >>> extract_version_info("Report_2024-01-15")
        ('Report', {'type': 'date', 'value': '2024-01-15', 'marker': '_2024-01-15'})
        
        >>> extract_version_info("Document")
        ('Document', None)
    """
    for pattern, version_type in VERSION_PATTERNS:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            # Extract base name by removing the matched pattern
            base_name = re.sub(pattern, '', filename, flags=re.IGNORECASE)
            base_name = base_name.strip('_- ')
            
            version_info = {
                "type": version_type,
                "value": match.group(1),
                "marker": match.group(0)
            }
            return base_name, version_info
    
    return filename, None


def clean_filename(filename: str, replacement: str = '_') -> str:
    """
    Clean a filename by removing or replacing unsafe characters.
    
    Removes characters that are not allowed in filenames on common
    operating systems (Windows, macOS, Linux).
    
    Args:
        filename: Filename to clean
        replacement: Character to replace unsafe characters with
        
    Returns:
        Cleaned filename safe for use on filesystem
        
    Example:
        >>> clean_filename('Report: Q1 2024?.pdf')
        'Report_ Q1 2024_.pdf'
        >>> clean_filename('file<name>.txt', replacement='-')
        'file-name-.txt'
    """
    # Replace unsafe characters
    cleaned = re.sub(UNSAFE_FILENAME_CHARS, replacement, filename)
    
    # Remove consecutive replacements
    while replacement + replacement in cleaned:
        cleaned = cleaned.replace(replacement + replacement, replacement)
    
    # Remove leading/trailing replacements and spaces
    cleaned = cleaned.strip(replacement + ' ')
    
    return cleaned


def extract_common_prefix(names: List[str]) -> str:
    """
    Find the longest common prefix from a list of strings.
    
    Useful for finding the base name from a group of version files.
    
    Args:
        names: List of strings to find common prefix from
        
    Returns:
        Longest common prefix string
        
    Example:
        >>> extract_common_prefix(["Budget_v1", "Budget_v2", "Budget_final"])
        'Budget_'
    """
    if not names:
        return ""
    
    if len(names) == 1:
        return names[0]
    
    common = names[0]
    for name in names[1:]:
        new_common = ""
        for c1, c2 in zip(common, name):
            if c1.lower() == c2.lower():
                new_common += c1
            else:
                break
        common = new_common
    
    return common


def clean_base_name(name: str) -> str:
    """
    Clean up a base name by removing trailing punctuation.
    
    Args:
        name: Name to clean
        
    Returns:
        Cleaned name with trailing punctuation removed
        
    Example:
        >>> clean_base_name("Budget_")
        'Budget'
        >>> clean_base_name("Report - (")
        'Report'
    """
    return name.strip('_- ()')


def extract_base_from_name(name: str) -> str:
    """
    Extract base name by removing version markers and parenthetical suffixes.
    
    More aggressive cleaning than extract_version_info, useful when
    the exact version pattern is unknown.
    
    Args:
        name: Filename to extract base from
        
    Returns:
        Base name with common suffixes removed
        
    Example:
        >>> extract_base_from_name("Budget_v2_final (1)")
        'Budget'
    """
    # Remove parenthetical suffixes like " (1)", " (revised)"
    base = re.sub(r'[_\-\s]*\([^)]*\)$', '', name)
    
    # Remove common version markers
    base = re.sub(
        r'[_\-\s]*(v|version|rev|draft|final)\d*$', 
        '', 
        base, 
        flags=re.IGNORECASE
    )
    
    return base.strip('_- ')


def get_status_priority(status: str) -> int:
    """
    Get the priority value for a version status marker.
    
    Lower values indicate older/earlier stages in the document lifecycle.
    
    Args:
        status: Status string (draft, wip, review, approved, final)
        
    Returns:
        Priority value (1-5), or 99 for unknown status
        
    Example:
        >>> get_status_priority("draft")
        1
        >>> get_status_priority("final")
        5
    """
    return STATUS_PRIORITY.get(status.lower(), 99)


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in a string.
    
    Replaces multiple consecutive whitespace characters with a single space
    and trims leading/trailing whitespace.
    
    Args:
        text: Text to normalize
        
    Returns:
        Text with normalized whitespace
        
    Example:
        >>> normalize_whitespace("Hello   World")
        'Hello World'
    """
    return ' '.join(text.split())


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate a string to a maximum length with suffix.
    
    Args:
        text: Text to truncate
        max_length: Maximum total length including suffix
        suffix: Suffix to append when truncating
        
    Returns:
        Truncated string or original if already short enough
        
    Example:
        >>> truncate_string("This is a long document title", 20)
        'This is a long do...'
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix
