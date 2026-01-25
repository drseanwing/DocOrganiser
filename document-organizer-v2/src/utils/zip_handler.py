# =============================================================================
# Document Organizer v2 - ZIP File Handler
# =============================================================================

"""
Utility module for handling ZIP file operations.

Provides functionality for:
- Extracting ZIP archives
- Creating ZIP archives from directories
- Validating ZIP file integrity
- Listing ZIP contents with metadata
"""

import asyncio
import hashlib
import zipfile
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import structlog

logger = structlog.get_logger(__name__)

# System files to skip during extraction/creation
SYSTEM_FILES = {
    '__MACOSX',
    '.DS_Store',
    'Thumbs.db',
    'desktop.ini',
    '._.DS_Store',
}


class ZipHandlerError(Exception):
    """Base exception for ZIP handler errors."""
    pass


class ZipHandler:
    """Handler for ZIP file operations with async support and robust error handling."""

    def __init__(self):
        """Initialize the ZIP handler."""
        self.logger = logger.bind(component="ZipHandler")

    def _should_skip_file(self, file_path: str) -> bool:
        """
        Check if a file should be skipped based on system file patterns.

        Args:
            file_path: Path to check

        Returns:
            True if file should be skipped, False otherwise
        """
        path = Path(file_path)
        # Check if any part of the path matches system files
        return any(part in SYSTEM_FILES for part in path.parts) or path.name in SYSTEM_FILES

    def _calculate_file_hash(self, file_path: Path, algorithm: str = 'sha256') -> str:
        """
        Calculate hash of a file.

        Args:
            file_path: Path to the file
            algorithm: Hash algorithm to use (default: sha256)

        Returns:
            Hexadecimal hash string
        """
        hash_func = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(8192), b''):
                hash_func.update(chunk)
        return hash_func.hexdigest()

    async def extract(
        self,
        zip_path: Path,
        dest_path: Path,
        calculate_hashes: bool = True
    ) -> List[Dict[str, any]]:
        """
        Extract ZIP file to destination directory.

        Args:
            zip_path: Path to ZIP file
            dest_path: Destination directory for extraction
            calculate_hashes: Whether to calculate file hashes (default: True)

        Returns:
            List of dictionaries with extracted file info:
            {
                'path': Path,
                'size': int,
                'hash': str (if calculate_hashes=True)
            }

        Raises:
            ZipHandlerError: If extraction fails
        """
        self.logger.info("extracting_zip", zip_path=str(zip_path), dest_path=str(dest_path))

        if not zip_path.exists():
            raise ZipHandlerError(f"ZIP file not found: {zip_path}")

        if not zipfile.is_zipfile(zip_path):
            raise ZipHandlerError(f"Invalid ZIP file: {zip_path}")

        # Create destination directory if it doesn't exist
        dest_path.mkdir(parents=True, exist_ok=True)

        extracted_files = []

        try:
            # Run extraction in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            extracted_files = await loop.run_in_executor(
                None,
                self._extract_sync,
                zip_path,
                dest_path,
                calculate_hashes
            )

            self.logger.info(
                "zip_extracted",
                zip_path=str(zip_path),
                files_count=len(extracted_files)
            )
            return extracted_files

        except zipfile.BadZipFile as e:
            raise ZipHandlerError(f"Corrupted ZIP file: {zip_path}") from e
        except PermissionError as e:
            raise ZipHandlerError(f"Permission denied: {e}") from e
        except Exception as e:
            raise ZipHandlerError(f"Failed to extract ZIP: {e}") from e

    def _extract_sync(
        self,
        zip_path: Path,
        dest_path: Path,
        calculate_hashes: bool
    ) -> List[Dict[str, any]]:
        """
        Synchronous extraction implementation.

        Args:
            zip_path: Path to ZIP file
            dest_path: Destination directory
            calculate_hashes: Whether to calculate file hashes

        Returns:
            List of extracted file info dictionaries
        """
        extracted_files = []

        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Get list of files, excluding system files
            for member in zf.namelist():
                if self._should_skip_file(member):
                    self.logger.debug("skipping_system_file", file=member)
                    continue

                # Extract the file
                try:
                    extracted_path = zf.extract(member, dest_path)
                    file_path = Path(extracted_path)

                    # Only process actual files, not directories
                    if file_path.is_file():
                        file_info = {
                            'path': file_path,
                            'size': file_path.stat().st_size,
                        }

                        if calculate_hashes:
                            file_info['hash'] = self._calculate_file_hash(file_path)

                        extracted_files.append(file_info)
                        self.logger.debug("file_extracted", file=member, size=file_info['size'])

                except Exception as e:
                    self.logger.warning("failed_to_extract_file", file=member, error=str(e))
                    continue

        return extracted_files

    async def create(
        self,
        source_dir: Path,
        zip_path: Path,
        compression: int = zipfile.ZIP_DEFLATED
    ) -> Path:
        """
        Create ZIP archive from directory.

        Args:
            source_dir: Directory to compress
            zip_path: Output ZIP file path
            compression: Compression method (default: ZIP_DEFLATED)

        Returns:
            Path to created ZIP file

        Raises:
            ZipHandlerError: If creation fails
        """
        self.logger.info("creating_zip", source_dir=str(source_dir), zip_path=str(zip_path))

        if not source_dir.exists():
            raise ZipHandlerError(f"Source directory not found: {source_dir}")

        if not source_dir.is_dir():
            raise ZipHandlerError(f"Source path is not a directory: {source_dir}")

        # Ensure parent directory exists
        zip_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Run creation in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._create_sync,
                source_dir,
                zip_path,
                compression
            )

            self.logger.info(
                "zip_created",
                zip_path=str(zip_path),
                size=zip_path.stat().st_size
            )
            return zip_path

        except PermissionError as e:
            raise ZipHandlerError(f"Permission denied: {e}") from e
        except Exception as e:
            raise ZipHandlerError(f"Failed to create ZIP: {e}") from e

    def _create_sync(
        self,
        source_dir: Path,
        zip_path: Path,
        compression: int
    ) -> None:
        """
        Synchronous ZIP creation implementation.

        Args:
            source_dir: Directory to compress
            zip_path: Output ZIP file path
            compression: Compression method
        """
        with zipfile.ZipFile(zip_path, 'w', compression=compression) as zf:
            # Walk through directory and add files
            for file_path in source_dir.rglob('*'):
                if file_path.is_file() and not self._should_skip_file(str(file_path)):
                    # Calculate relative path for archive
                    arcname = file_path.relative_to(source_dir)
                    try:
                        zf.write(file_path, arcname)
                        self.logger.debug("file_added_to_zip", file=str(arcname))
                    except Exception as e:
                        self.logger.warning(
                            "failed_to_add_file",
                            file=str(arcname),
                            error=str(e)
                        )
                        continue

    async def validate(self, zip_path: Path) -> Tuple[bool, str]:
        """
        Validate ZIP file integrity.

        Args:
            zip_path: Path to ZIP file to validate

        Returns:
            Tuple of (is_valid: bool, message: str)
        """
        self.logger.info("validating_zip", zip_path=str(zip_path))

        if not zip_path.exists():
            return False, f"ZIP file not found: {zip_path}"

        if not zipfile.is_zipfile(zip_path):
            return False, f"Not a valid ZIP file: {zip_path}"

        try:
            # Run validation in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._validate_sync,
                zip_path
            )
            return result

        except Exception as e:
            error_msg = f"Validation error: {e}"
            self.logger.error("validation_failed", zip_path=str(zip_path), error=str(e))
            return False, error_msg

    def _validate_sync(self, zip_path: Path) -> Tuple[bool, str]:
        """
        Synchronous ZIP validation implementation.

        Args:
            zip_path: Path to ZIP file

        Returns:
            Tuple of (is_valid, message)
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # testzip() returns the name of the first bad file, or None
                bad_file = zf.testzip()
                if bad_file is not None:
                    return False, f"Corrupted file in archive: {bad_file}"

            self.logger.info("zip_valid", zip_path=str(zip_path))
            return True, "ZIP file is valid"

        except zipfile.BadZipFile as e:
            return False, f"Bad ZIP file: {e}"
        except Exception as e:
            return False, f"Validation error: {e}"

    async def list_contents(self, zip_path: Path) -> List[Dict[str, any]]:
        """
        List contents of ZIP file with metadata.

        Args:
            zip_path: Path to ZIP file

        Returns:
            List of dictionaries with file info:
            {
                'name': str,
                'size': int,  # uncompressed size
                'compressed_size': int,
                'compression_ratio': float,  # percentage
                'is_dir': bool,
                'date_time': tuple  # (year, month, day, hour, minute, second)
            }

        Raises:
            ZipHandlerError: If listing fails
        """
        self.logger.info("listing_zip_contents", zip_path=str(zip_path))

        if not zip_path.exists():
            raise ZipHandlerError(f"ZIP file not found: {zip_path}")

        if not zipfile.is_zipfile(zip_path):
            raise ZipHandlerError(f"Invalid ZIP file: {zip_path}")

        try:
            # Run listing in thread pool
            loop = asyncio.get_event_loop()
            contents = await loop.run_in_executor(
                None,
                self._list_contents_sync,
                zip_path
            )

            self.logger.info("zip_contents_listed", zip_path=str(zip_path), items=len(contents))
            return contents

        except zipfile.BadZipFile as e:
            raise ZipHandlerError(f"Corrupted ZIP file: {zip_path}") from e
        except Exception as e:
            raise ZipHandlerError(f"Failed to list ZIP contents: {e}") from e

    def _list_contents_sync(self, zip_path: Path) -> List[Dict[str, any]]:
        """
        Synchronous ZIP contents listing implementation.

        Args:
            zip_path: Path to ZIP file

        Returns:
            List of file info dictionaries
        """
        contents = []

        with zipfile.ZipFile(zip_path, 'r') as zf:
            for info in zf.infolist():
                # Skip system files
                if self._should_skip_file(info.filename):
                    continue

                # Calculate compression ratio
                compression_ratio = 0.0
                if info.file_size > 0:
                    compression_ratio = (
                        1 - (info.compress_size / info.file_size)
                    ) * 100

                file_info = {
                    'name': info.filename,
                    'size': info.file_size,
                    'compressed_size': info.compress_size,
                    'compression_ratio': round(compression_ratio, 2),
                    'is_dir': info.is_dir(),
                    'date_time': info.date_time,
                }

                contents.append(file_info)

        return contents
