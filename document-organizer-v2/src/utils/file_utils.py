"""
File Utilities Module.

Provides reusable functions for file system operations including:
- Directory walking and file discovery
- File filtering by extension and size
- Path normalization and manipulation

Extracted from inline implementations in IndexAgent for reusability.
"""

import os
from pathlib import Path
from typing import List, Set, Optional, Union, Iterator, Callable
import structlog


logger = structlog.get_logger("file_utils")


def walk_directory(
    root: Union[str, Path],
    include_hidden: bool = False,
    follow_symlinks: bool = False
) -> Iterator[Path]:
    """
    Recursively walk a directory tree and yield file paths.
    
    Yields all files (not directories) under the given root path.
    
    Args:
        root: Root directory to start walking from
        include_hidden: Include hidden files (starting with . or ~)
        follow_symlinks: Follow symbolic links when walking
        
    Yields:
        Path objects for each file found
        
    Example:
        >>> for file_path in walk_directory("/data/source"):
        ...     print(file_path)
        /data/source/doc1.pdf
        /data/source/subfolder/doc2.docx
    """
    root = Path(root)
    
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        
        # Skip hidden files unless explicitly included
        if not include_hidden:
            if path.name.startswith('.') or path.name.startswith('~'):
                continue
        
        # Handle symlinks
        if path.is_symlink() and not follow_symlinks:
            continue
        
        yield path


def filter_by_extension(
    files: Iterator[Path],
    extensions: Optional[Set[str]] = None,
    exclude_extensions: Optional[Set[str]] = None
) -> Iterator[Path]:
    """
    Filter files by their extension.
    
    Args:
        files: Iterator of Path objects to filter
        extensions: Set of allowed extensions (without dot, lowercase).
                   If None, all extensions are allowed.
        exclude_extensions: Set of extensions to exclude (without dot, lowercase).
                           Applied after inclusion filter.
        
    Yields:
        Path objects that match the extension criteria
        
    Example:
        >>> files = walk_directory("/data")
        >>> pdf_files = filter_by_extension(files, extensions={"pdf", "docx"})
        >>> for f in pdf_files:
        ...     print(f)
    """
    for file_path in files:
        ext = file_path.suffix.lower().lstrip('.')
        
        # Check inclusion filter
        if extensions is not None and ext not in extensions:
            continue
        
        # Check exclusion filter
        if exclude_extensions is not None and ext in exclude_extensions:
            continue
        
        yield file_path


def filter_by_size(
    files: Iterator[Path],
    min_size: Optional[int] = None,
    max_size: Optional[int] = None
) -> Iterator[Path]:
    """
    Filter files by their size in bytes.
    
    Args:
        files: Iterator of Path objects to filter
        min_size: Minimum file size in bytes (inclusive). None for no minimum.
        max_size: Maximum file size in bytes (inclusive). None for no maximum.
        
    Yields:
        Path objects that match the size criteria
        
    Example:
        >>> files = walk_directory("/data")
        >>> # Files between 1KB and 100MB
        >>> sized_files = filter_by_size(files, min_size=1024, max_size=100*1024*1024)
    """
    for file_path in files:
        try:
            size = file_path.stat().st_size
        except OSError:
            # Skip files we can't stat
            continue
        
        if min_size is not None and size < min_size:
            continue
        
        if max_size is not None and size > max_size:
            continue
        
        yield file_path


def get_relative_path(file_path: Union[str, Path], base_path: Union[str, Path]) -> str:
    """
    Get the relative path of a file from a base directory.
    
    Args:
        file_path: Absolute or relative path to the file
        base_path: Base directory to calculate relative path from
        
    Returns:
        Relative path as a string with forward slashes
        
    Raises:
        ValueError: If file_path is not under base_path
        
    Example:
        >>> get_relative_path("/data/source/docs/file.pdf", "/data/source")
        'docs/file.pdf'
    """
    file_path = Path(file_path).resolve()
    base_path = Path(base_path).resolve()
    
    relative = file_path.relative_to(base_path)
    return str(relative).replace('\\', '/')


def normalize_path(path: Union[str, Path]) -> str:
    """
    Normalize a path for cross-platform compatibility.
    
    - Converts backslashes to forward slashes
    - Resolves . and .. components
    - Removes trailing slashes
    
    Args:
        path: Path to normalize
        
    Returns:
        Normalized path string with forward slashes
        
    Example:
        >>> normalize_path("docs\\subfolder\\..\\file.pdf")
        'docs/file.pdf'
    """
    normalized = os.path.normpath(str(path))
    # Convert to forward slashes for consistency
    return normalized.replace('\\', '/')


def get_file_extension(file_path: Union[str, Path]) -> str:
    """
    Get the lowercase extension of a file without the leading dot.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Lowercase extension without dot, empty string if no extension
        
    Example:
        >>> get_file_extension("/path/to/Document.PDF")
        'pdf'
        >>> get_file_extension("/path/to/README")
        ''
    """
    return Path(file_path).suffix.lower().lstrip('.')


def collect_files(
    root: Union[str, Path],
    extensions: Optional[Set[str]] = None,
    max_size: Optional[int] = None,
    include_hidden: bool = False
) -> List[Path]:
    """
    Collect all files matching the specified criteria.
    
    Convenience function that combines walk_directory, filter_by_extension,
    and filter_by_size into a single call.
    
    Args:
        root: Root directory to search
        extensions: Set of allowed extensions (lowercase, without dot)
        max_size: Maximum file size in bytes
        include_hidden: Include hidden files
        
    Returns:
        List of Path objects matching all criteria
        
    Example:
        >>> files = collect_files(
        ...     "/data/source",
        ...     extensions={"pdf", "docx", "xlsx"},
        ...     max_size=100*1024*1024  # 100MB
        ... )
    """
    files = walk_directory(root, include_hidden=include_hidden)
    
    if extensions:
        files = filter_by_extension(files, extensions=extensions)
    
    if max_size:
        files = filter_by_size(files, max_size=max_size)
    
    return list(files)


def ensure_directory(path: Union[str, Path]) -> Path:
    """
    Ensure a directory exists, creating it if necessary.
    
    Args:
        path: Directory path to ensure exists
        
    Returns:
        Path object for the directory
        
    Example:
        >>> ensure_directory("/data/output/reports")
        Path('/data/output/reports')
    """
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path
