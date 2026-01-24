"""
Manifest Generator for Document Organizer v2.

Generates comprehensive manifests tracking all file operations for:
- Audit trail
- Rollback support
- Reporting
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import structlog


class ManifestGenerator:
    """Generates execution manifests tracking all file operations."""
    
    def __init__(self):
        self.logger = structlog.get_logger("manifest_generator")
        self.operations: List[Dict] = []
        self.shortcuts: List[Dict] = []
        self.errors: List[Dict] = []
        self.statistics: Dict = {
            "total_files": 0,
            "directories_created": 0,
            "files_copied": 0,
            "files_renamed": 0,
            "files_moved": 0,
            "shortcuts_created": 0,
            "version_archives": 0,
            "errors": 0
        }
    
    def add_operation(
        self,
        operation_type: str,
        source_path: Optional[str] = None,
        target_path: Optional[str] = None,
        document_id: Optional[int] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        Add an operation to the manifest.
        
        Args:
            operation_type: Type of operation ('create_dir', 'copy', 'rename', 'move', 'create_shortcut')
            source_path: Source file/directory path
            target_path: Target file/directory path
            document_id: Associated document ID
            success: Whether the operation succeeded
            error: Error message if operation failed
        """
        operation = {
            "type": operation_type,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if source_path:
            operation["source"] = source_path
        if target_path:
            operation["target"] = target_path
        if document_id:
            operation["document_id"] = document_id
        
        operation["success"] = success
        if error:
            operation["error"] = error
        
        self.operations.append(operation)
        
        # Update statistics
        if success:
            if operation_type == "create_dir":
                self.statistics["directories_created"] += 1
            elif operation_type == "copy":
                self.statistics["files_copied"] += 1
            elif operation_type == "rename":
                self.statistics["files_renamed"] += 1
            elif operation_type == "move":
                self.statistics["files_moved"] += 1
            elif operation_type == "create_shortcut":
                self.statistics["shortcuts_created"] += 1
        else:
            self.statistics["errors"] += 1
    
    def add_shortcut(
        self,
        shortcut_path: str,
        target_path: str,
        original_path: str,
        shortcut_type: str
    ):
        """
        Add a shortcut to the manifest.
        
        Args:
            shortcut_path: Path where shortcut was created
            target_path: Path to target file
            original_path: Original path of duplicate file
            shortcut_type: Type of shortcut created
        """
        self.shortcuts.append({
            "shortcut_path": shortcut_path,
            "target_path": target_path,
            "original_path": original_path,
            "shortcut_type": shortcut_type,
            "created_at": datetime.utcnow().isoformat()
        })
    
    def add_error(
        self,
        document_id: Optional[int],
        error: str,
        source: Optional[str] = None,
        operation: Optional[str] = None
    ):
        """
        Add an error to the manifest.
        
        Args:
            document_id: Associated document ID
            error: Error message
            source: Source path that caused the error
            operation: Operation that failed
        """
        error_entry = {
            "error": error,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if document_id:
            error_entry["document_id"] = document_id
        if source:
            error_entry["source"] = source
        if operation:
            error_entry["operation"] = operation
        
        self.errors.append(error_entry)
    
    def set_total_files(self, count: int):
        """Set the total number of files being processed."""
        self.statistics["total_files"] = count
    
    def increment_version_archives(self):
        """Increment the version archives counter."""
        self.statistics["version_archives"] += 1
    
    def generate_manifest(
        self,
        job_id: str,
        source_zip: Optional[str],
        output_path: Path
    ) -> Path:
        """
        Generate the complete manifest file.
        
        Args:
            job_id: Processing job ID
            source_zip: Original ZIP file name
            output_path: Path where manifest should be saved
            
        Returns:
            Path to the generated manifest file
        """
        manifest = {
            "job_id": job_id,
            "executed_at": datetime.utcnow().isoformat(),
            "source_zip": source_zip,
            "statistics": self.statistics,
            "operations": self.operations,
            "shortcuts": self.shortcuts,
            "errors": self.errors
        }
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write manifest
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        self.logger.info(
            "manifest_generated",
            path=str(output_path),
            operations=len(self.operations),
            shortcuts=len(self.shortcuts),
            errors=len(self.errors)
        )
        
        return output_path
    
    def get_summary(self) -> Dict:
        """
        Get a summary of operations.
        
        Returns:
            Dictionary with operation statistics
        """
        return {
            **self.statistics,
            "operations_count": len(self.operations),
            "shortcuts_count": len(self.shortcuts),
            "errors_count": len(self.errors)
        }
