"""
Utilities Module.

Provides reusable utility functions for the DocOrganiser system.

Modules:
- hashing: SHA256 and MD5 hashing for files and content
- file_utils: File system operations, directory walking, filtering
- string_utils: String similarity, version extraction, filename sanitization
"""

from src.utils.hashing import (
    hash_file,
    hash_content,
    hash_file_md5,
    hash_string_md5,
)

from src.utils.file_utils import (
    walk_directory,
    filter_by_extension,
    filter_by_size,
    get_relative_path,
    normalize_path,
    get_file_extension,
    collect_files,
    ensure_directory,
)

from src.utils.string_utils import (
    levenshtein_similarity,
    extract_version_info,
    clean_filename,
    extract_common_prefix,
    clean_base_name,
    extract_base_from_name,
    get_status_priority,
    normalize_whitespace,
    truncate_string,
    VERSION_PATTERNS,
    STATUS_PRIORITY,
)

__all__ = [
    # Hashing utilities
    'hash_file',
    'hash_content',
    'hash_file_md5',
    'hash_string_md5',
    
    # File utilities
    'walk_directory',
    'filter_by_extension',
    'filter_by_size',
    'get_relative_path',
    'normalize_path',
    'get_file_extension',
    'collect_files',
    'ensure_directory',
    
    # String utilities
    'levenshtein_similarity',
    'extract_version_info',
    'clean_filename',
    'extract_common_prefix',
    'clean_base_name',
    'extract_base_from_name',
    'get_status_priority',
    'normalize_whitespace',
    'truncate_string',
    'VERSION_PATTERNS',
    'STATUS_PRIORITY',
]
