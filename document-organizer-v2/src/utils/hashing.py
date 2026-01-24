"""
Hashing Utilities Module.

Provides reusable functions for calculating SHA256 hashes of files and content.
Extracted from inline implementations in IndexAgent and main.py for reusability.
"""

import hashlib
from pathlib import Path
from typing import Union


# Default chunk size for reading files (8KB)
DEFAULT_CHUNK_SIZE = 8192


def hash_file(file_path: Union[str, Path], chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """
    Calculate SHA256 hash of a file's content.
    
    Reads file in chunks to handle large files efficiently without
    loading entire content into memory.
    
    Args:
        file_path: Path to the file to hash
        chunk_size: Size of chunks to read (default: 8192 bytes)
        
    Returns:
        Hexadecimal SHA256 hash string (64 characters)
        
    Raises:
        FileNotFoundError: If file does not exist
        PermissionError: If file cannot be read
        IsADirectoryError: If path is a directory
        
    Example:
        >>> hash_file("/path/to/document.pdf")
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    """
    file_path = Path(file_path)
    sha256 = hashlib.sha256()
    
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            sha256.update(chunk)
    
    return sha256.hexdigest()


def hash_content(content: Union[str, bytes]) -> str:
    """
    Calculate SHA256 hash of content (string or bytes).
    
    Useful for hashing in-memory content without writing to disk.
    
    Args:
        content: String or bytes to hash. Strings are encoded as UTF-8.
        
    Returns:
        Hexadecimal SHA256 hash string (64 characters)
        
    Example:
        >>> hash_content("Hello, World!")
        'dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f'
        
        >>> hash_content(b"Binary data")
        'a1b2c3...'
    """
    if isinstance(content, str):
        content = content.encode('utf-8')
    
    return hashlib.sha256(content).hexdigest()


def hash_file_md5(file_path: Union[str, Path], chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """
    Calculate MD5 hash of a file's content.
    
    Useful for generating unique identifiers from file paths or
    for compatibility with systems requiring MD5 hashes.
    
    Note: MD5 should not be used for security-sensitive applications.
    
    Args:
        file_path: Path to the file to hash
        chunk_size: Size of chunks to read (default: 8192 bytes)
        
    Returns:
        Hexadecimal MD5 hash string (32 characters)
        
    Example:
        >>> hash_file_md5("/path/to/document.pdf")
        'd41d8cd98f00b204e9800998ecf8427e'
    """
    file_path = Path(file_path)
    md5 = hashlib.md5()
    
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            md5.update(chunk)
    
    return md5.hexdigest()


def hash_string_md5(content: str) -> str:
    """
    Calculate MD5 hash of a string.
    
    Commonly used for generating unique identifiers from paths or names.
    
    Note: MD5 should not be used for security-sensitive applications.
    
    Args:
        content: String to hash
        
    Returns:
        Hexadecimal MD5 hash string (32 characters)
        
    Example:
        >>> hash_string_md5("path/to/file.txt")
        'a1b2c3d4e5f6...'
    """
    return hashlib.md5(content.encode('utf-8')).hexdigest()
