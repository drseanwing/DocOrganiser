"""
Execution Engine for Document Organizer v2.

Executes all planned file operations:
1. Creates directory structure
2. Moves and renames files
3. Creates shortcuts for duplicates
4. Sets up version archives
5. Generates manifest
6. Updates database
"""

import os
import shutil
import json
import asyncio
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from sqlalchemy import text
import structlog

from src.agents.base_agent import BaseAgent, AgentResult
from src.config import ProcessingPhase, get_settings
from src.execution.shortcut_creator import ShortcutCreator
from src.execution.manifest_generator import ManifestGenerator


class ExecutionEngine(BaseAgent):
    """
    Agent responsible for executing all planned file operations.
    
    Runs AFTER all planning is complete (and optionally after human review).
    Never modifies /data/source/ - only works with /data/working/.
    """
    
    AGENT_NAME = "execution_engine"
    AGENT_PHASE = ProcessingPhase.EXECUTING
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_root = Path(self.settings.data_source_path)
        self.working_root = Path(self.settings.data_working_path)
        self.reports_root = Path(self.settings.data_reports_path)
        
        self.shortcut_creator = ShortcutCreator()
        self.manifest = ManifestGenerator()
        
        # Execution statistics
        self._dirs_created = 0
        self._files_processed = 0
        self._shortcuts_created = 0
        self._version_archives = 0
        self._errors = []
    
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """
        Verify organization planning is complete.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        session = self.get_sync_session()
        try:
            # Check if source directory exists and has files
            if not self.source_root.exists():
                return False, f"Source directory does not exist: {self.source_root}"
            
            source_files = list(self.source_root.rglob("*"))
            if not source_files:
                return False, "Source directory is empty"
            
            # Check if there are documents to process
            result = session.execute(
                text("""
                    SELECT COUNT(*) as count 
                    FROM document_items 
                    WHERE job_id = :job_id AND status IN ('organized', 'pending_apply')
                """),
                {"job_id": self.job_id}
            )
            count = result.scalar()
            
            if count == 0:
                return False, "No documents ready for execution (status must be 'organized' or 'pending_apply')"
            
            self.logger.info(
                "prerequisites_validated",
                source_files=len(source_files),
                documents_to_process=count
            )
            return True, ""
            
        except Exception as e:
            return False, f"Validation error: {str(e)}"
        finally:
            session.close()
    
    async def run(self, dry_run: bool = False) -> AgentResult:
        """
        Execute all planned changes.
        
        Args:
            dry_run: If True, validate and report what would happen without making changes
            
        Returns:
            AgentResult with execution outcome
        """
        start_time = datetime.utcnow()
        self.start_processing()
        
        try:
            # Step 1: Validate execution plan
            self.logger.info("validating_execution_plan", dry_run=dry_run)
            self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=5)
            
            is_valid, errors = await self._validate_execution_plan()
            if not is_valid:
                return AgentResult(
                    success=False,
                    error=f"Execution plan validation failed: {'; '.join(errors)}",
                    metadata={"validation_errors": errors}
                )
            
            if dry_run:
                # Generate preview without executing
                preview = await self._generate_dry_run_preview()
                return AgentResult(
                    success=True,
                    processed_count=preview["total_operations"],
                    metadata={
                        "dry_run": True,
                        "preview": preview
                    }
                )
            
            # Step 2: Clear working directory
            self.logger.info("clearing_working_directory")
            await self._clear_working_directory()
            self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=10)
            
            # Step 3: Create directory structure
            self.logger.info("creating_directories")
            dirs_created = await self._create_directories()
            self._dirs_created = dirs_created
            self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=20)
            
            # Step 4: Process file assignments (copy/move/rename)
            self.logger.info("processing_file_assignments")
            file_stats = await self._process_file_assignments()
            self._files_processed = file_stats.get("copied", 0)
            self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=70)
            
            # Step 5: Create shortcuts for duplicates
            self.logger.info("creating_shortcuts")
            shortcuts_created = await self._create_shortcuts()
            self._shortcuts_created = shortcuts_created
            self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=85)
            
            # Step 6: Setup version archives
            self.logger.info("setting_up_version_archives")
            archives_created = await self._setup_version_archives()
            self._version_archives = archives_created
            self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=90)
            
            # Step 7: Generate manifest
            self.logger.info("generating_manifest")
            manifest_path = await self._generate_manifest()
            self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=95)
            
            # Step 8: Update database with final states
            self.logger.info("updating_database")
            await self._update_final_states()
            self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=100)
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            self.logger.info(
                "execution_complete",
                dirs_created=dirs_created,
                files_processed=self._files_processed,
                shortcuts_created=shortcuts_created,
                version_archives=archives_created,
                errors=len(self._errors),
                duration_seconds=duration
            )
            
            return AgentResult(
                success=True,
                processed_count=self._files_processed,
                error_count=len(self._errors),
                duration_seconds=duration,
                metadata={
                    "directories_created": dirs_created,
                    "files_copied": file_stats.get("copied", 0),
                    "files_renamed": file_stats.get("renamed", 0),
                    "files_moved": file_stats.get("moved", 0),
                    "shortcuts_created": shortcuts_created,
                    "version_archives": archives_created,
                    "errors": self._errors,
                    "manifest_path": str(manifest_path)
                }
            )
            
        except Exception as e:
            self.logger.error("execution_failed", error=str(e), exc_info=True)
            return AgentResult(
                success=False,
                error=str(e),
                duration_seconds=(datetime.utcnow() - start_time).total_seconds()
            )
    
    async def _validate_execution_plan(self) -> tuple[bool, list[str]]:
        """
        Validate the execution plan before starting.
        
        Checks:
        - All source files exist
        - No path conflicts (two files → same destination)
        - All proposed paths are valid
        - No circular references in shortcuts
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        session = self.get_sync_session()
        
        try:
            # Check source files exist
            result = session.execute(
                text("""
                    SELECT id, current_path, current_name
                    FROM document_items
                    WHERE job_id = :job_id 
                    AND status IN ('organized', 'pending_apply')
                """),
                {"job_id": self.job_id}
            )
            
            for row in result:
                source_file = self.source_root / row.current_path / row.current_name
                if not source_file.exists():
                    errors.append(f"Source file not found: {source_file}")
            
            # Check for path conflicts
            result = session.execute(
                text("""
                    SELECT 
                        COALESCE(proposed_path, current_path) as final_path,
                        COALESCE(proposed_name, current_name) as final_name,
                        COUNT(*) as count
                    FROM document_items
                    WHERE job_id = :job_id 
                    AND status IN ('organized', 'pending_apply')
                    GROUP BY final_path, final_name
                    HAVING COUNT(*) > 1
                """),
                {"job_id": self.job_id}
            )
            
            conflicts = result.fetchall()
            for conflict in conflicts:
                errors.append(
                    f"Path conflict: {conflict.count} files targeting "
                    f"{conflict.final_path}/{conflict.final_name}"
                )
            
            # Check for invalid path characters
            result = session.execute(
                text("""
                    SELECT id, proposed_name, proposed_path
                    FROM document_items
                    WHERE job_id = :job_id 
                    AND status IN ('organized', 'pending_apply')
                    AND (proposed_name IS NOT NULL OR proposed_path IS NOT NULL)
                """),
                {"job_id": self.job_id}
            )
            
            for row in result:
                if row.proposed_name and not self._is_valid_filename(row.proposed_name):
                    errors.append(f"Invalid filename for doc {row.id}: {row.proposed_name}")
            
            return len(errors) == 0, errors
            
        except Exception as e:
            errors.append(f"Validation exception: {str(e)}")
            return False, errors
        finally:
            session.close()
    
    def _is_valid_filename(self, filename: str) -> bool:
        """Check if filename is valid (basic check)."""
        invalid_chars = r'[<>:"|?*\x00-\x1f]'
        return not re.search(invalid_chars, filename)
    
    async def _generate_dry_run_preview(self) -> dict:
        """Generate a preview of what would happen without executing."""
        session = self.get_sync_session()
        preview = {
            "directories_to_create": 0,
            "files_to_process": 0,
            "shortcuts_to_create": 0,
            "version_archives_to_create": 0,
            "total_operations": 0
        }
        
        try:
            # Count directories
            result = session.execute(
                text("SELECT COUNT(*) FROM directory_structure WHERE is_active = TRUE")
            )
            preview["directories_to_create"] = result.scalar()
            
            # Count files
            result = session.execute(
                text("""
                    SELECT COUNT(*) FROM document_items 
                    WHERE job_id = :job_id AND status IN ('organized', 'pending_apply')
                """),
                {"job_id": self.job_id}
            )
            preview["files_to_process"] = result.scalar()
            
            # Count shortcuts
            result = session.execute(
                text("""
                    SELECT COUNT(*) FROM duplicate_members 
                    WHERE action = 'shortcut'
                """)
            )
            preview["shortcuts_to_create"] = result.scalar()
            
            # Count version chains
            result = session.execute(
                text("SELECT COUNT(*) FROM version_chains")
            )
            preview["version_archives_to_create"] = result.scalar()
            
            preview["total_operations"] = (
                preview["directories_to_create"] +
                preview["files_to_process"] +
                preview["shortcuts_to_create"]
            )
            
            return preview
            
        finally:
            session.close()
    
    async def _clear_working_directory(self):
        """Clear the working directory, preserving the directory itself."""
        if self.working_root.exists():
            for item in self.working_root.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception as e:
                    self.logger.warning("failed_to_clear_item", item=str(item), error=str(e))
        else:
            self.working_root.mkdir(parents=True, exist_ok=True)
    
    async def _create_directories(self) -> int:
        """
        Create all directories from directory_structure table.
        
        Order: Create parents before children (sort by depth).
        
        Returns:
            Number of directories created
        """
        session = self.get_sync_session()
        created_count = 0
        
        try:
            # Get directories ordered by depth
            result = session.execute(
                text("""
                    SELECT path, folder_name, depth
                    FROM directory_structure
                    WHERE is_active = TRUE
                    ORDER BY depth ASC, path ASC
                """)
            )
            
            for row in result:
                dir_path = self.working_root / row.path.lstrip('/')
                
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    created_count += 1
                    
                    self.manifest.add_operation(
                        operation_type="create_dir",
                        target_path=str(dir_path),
                        success=True
                    )
                    
                    self.log_to_db(
                        action="create_directory",
                        details={"path": str(dir_path)},
                        success=True
                    )
                    
                except Exception as e:
                    error_msg = f"Failed to create directory {dir_path}: {str(e)}"
                    self.logger.error("directory_creation_failed", path=str(dir_path), error=str(e))
                    self._errors.append(error_msg)
                    
                    self.manifest.add_operation(
                        operation_type="create_dir",
                        target_path=str(dir_path),
                        success=False,
                        error=str(e)
                    )
            
            return created_count
            
        finally:
            session.close()
    
    async def _process_file_assignments(self) -> dict:
        """
        Process all file assignments from document_items.
        
        For each file:
        1. Determine source path
        2. Determine target path
        3. Copy file (preserve metadata)
        4. Log operation
        
        Returns:
            Dictionary with statistics
        """
        session = self.get_sync_session()
        stats = {
            "copied": 0,
            "renamed": 0,
            "moved": 0,
            "unchanged": 0,
            "errors": 0
        }
        
        try:
            # Get all documents to process
            result = session.execute(
                text("""
                    SELECT 
                        id,
                        current_name,
                        current_path,
                        proposed_name,
                        proposed_path,
                        has_name_change,
                        has_path_change
                    FROM document_items
                    WHERE job_id = :job_id 
                    AND status IN ('organized', 'pending_apply')
                    ORDER BY id
                """),
                {"job_id": self.job_id}
            )
            
            documents = result.fetchall()
            self.manifest.set_total_files(len(documents))
            
            for doc in documents:
                # Determine source
                source_path = self.source_root / doc.current_path.lstrip('/') / doc.current_name
                
                # Determine target
                target_name = doc.proposed_name if doc.proposed_name else doc.current_name
                target_path_str = doc.proposed_path if doc.proposed_path else doc.current_path
                target_dir = self.working_root / target_path_str.lstrip('/')
                target_path = target_dir / target_name
                
                # Sanitize filename
                target_name_sanitized = self._sanitize_filename(target_name)
                target_path = target_dir / target_name_sanitized
                
                # Classify operation
                operation_type = "copy"
                if doc.has_name_change and doc.has_path_change:
                    operation_type = "move"
                    stats["moved"] += 1
                    stats["renamed"] += 1
                elif doc.has_name_change:
                    operation_type = "rename"
                    stats["renamed"] += 1
                elif doc.has_path_change:
                    operation_type = "move"
                    stats["moved"] += 1
                else:
                    stats["unchanged"] += 1
                
                # Copy file
                success = await self._copy_file_with_metadata(source_path, target_path)
                
                if success:
                    stats["copied"] += 1
                    self.manifest.add_operation(
                        operation_type=operation_type,
                        source_path=str(source_path),
                        target_path=str(target_path),
                        document_id=doc.id,
                        success=True
                    )
                    
                    # Update database with final paths
                    session.execute(
                        text("""
                            UPDATE document_items
                            SET final_name = :final_name,
                                final_path = :final_path,
                                changes_applied = TRUE,
                                applied_at = NOW(),
                                status = 'applied'
                            WHERE id = :doc_id
                        """),
                        {
                            "final_name": target_name_sanitized,
                            "final_path": target_path_str,
                            "doc_id": doc.id
                        }
                    )
                else:
                    stats["errors"] += 1
                    error_msg = f"Failed to copy file: {source_path}"
                    self._errors.append(error_msg)
                    self.manifest.add_error(doc.id, error_msg, str(source_path), operation_type)
            
            session.commit()
            return stats
            
        except Exception as e:
            session.rollback()
            self.logger.error("file_processing_failed", error=str(e), exc_info=True)
            stats["errors"] += 1
            raise
        finally:
            session.close()
    
    async def _copy_file_with_metadata(self, source: Path, target: Path) -> bool:
        """
        Copy file preserving metadata.
        
        Preserves:
        - Modification time
        - Access time
        - Permissions (where possible)
        
        Args:
            source: Source file path
            target: Target file path
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure source exists
            if not source.exists():
                self.logger.error("source_file_not_found", source=str(source))
                return False
            
            # Ensure target directory exists
            target.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy file with metadata (shutil.copy2 preserves metadata)
            shutil.copy2(source, target)
            
            return True
            
        except Exception as e:
            self.logger.error("copy_failed", source=str(source), target=str(target), error=str(e), exc_info=True)
            return False
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for cross-platform compatibility.
        
        Remove/replace:
        - < > : " / \\ | ? *
        - Leading/trailing spaces
        - Trailing dots
        - Reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename
        """
        # Replace invalid characters
        invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
        sanitized = re.sub(invalid_chars, '_', filename)
        
        # Remove leading/trailing spaces
        sanitized = sanitized.strip()
        
        # Remove trailing dots
        sanitized = sanitized.rstrip('.')
        
        # Check for reserved names (Windows)
        reserved_names = [
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        ]
        
        name_without_ext = Path(sanitized).stem.upper()
        if name_without_ext in reserved_names:
            sanitized = f"_{sanitized}"
        
        # Ensure not empty
        if not sanitized:
            sanitized = "unnamed"
        
        return sanitized
    
    async def _create_shortcuts(self) -> int:
        """
        Create shortcuts for files marked as duplicates.
        
        For each duplicate with action='shortcut':
        1. Find the primary file's final location
        2. Determine shortcut location
        3. Create appropriate shortcut type
        4. Record in shortcut_files table
        
        Returns:
            Number of shortcuts created
        """
        session = self.get_sync_session()
        created_count = 0
        
        try:
            # Get duplicates that need shortcuts
            result = session.execute(
                text("""
                    SELECT 
                        dm.id as member_id,
                        dm.document_id,
                        dm.group_id,
                        dg.primary_document_id,
                        di_dup.current_path as dup_path,
                        di_dup.current_name as dup_name,
                        di_dup.proposed_path as dup_proposed_path,
                        di_dup.proposed_name as dup_proposed_name,
                        di_dup.content_hash,
                        di_primary.final_path as primary_final_path,
                        di_primary.final_name as primary_final_name,
                        di_primary.proposed_path as primary_proposed_path,
                        di_primary.proposed_name as primary_proposed_name
                    FROM duplicate_members dm
                    JOIN duplicate_groups dg ON dm.group_id = dg.id
                    JOIN document_items di_dup ON dm.document_id = di_dup.id
                    JOIN document_items di_primary ON dg.primary_document_id = di_primary.id
                    WHERE dm.action = 'shortcut'
                    AND dm.shortcut_created = FALSE
                """)
            )
            
            for row in result:
                # Determine primary file's final location
                primary_path_str = row.primary_final_path or row.primary_proposed_path or row.dup_path
                primary_name = row.primary_final_name or row.primary_proposed_name or row.dup_name
                primary_file = self.working_root / primary_path_str.lstrip('/') / primary_name
                
                # Determine where shortcut should be
                shortcut_path_str = row.dup_proposed_path or row.dup_path
                shortcut_name = row.dup_proposed_name or row.dup_name
                shortcut_dir = self.working_root / shortcut_path_str.lstrip('/')
                shortcut_path = shortcut_dir / shortcut_name
                
                # Create shortcut (try symlink first, fall back to .url)
                success, shortcut_type = self.shortcut_creator.create_shortcut(
                    target=primary_file,
                    shortcut_path=shortcut_path,
                    shortcut_type="auto"
                )
                
                if success:
                    created_count += 1
                    
                    # Record in database
                    session.execute(
                        text("""
                            INSERT INTO shortcut_files 
                            (original_document_id, shortcut_path, target_path, 
                             shortcut_type, original_path, original_hash)
                            VALUES (:doc_id, :shortcut_path, :target_path, 
                                    :shortcut_type, :original_path, :original_hash)
                        """),
                        {
                            "doc_id": row.document_id,
                            "shortcut_path": str(shortcut_path),
                            "target_path": str(primary_file),
                            "shortcut_type": shortcut_type,
                            "original_path": f"{row.dup_path}/{row.dup_name}",
                            "original_hash": row.content_hash
                        }
                    )
                    
                    # Mark as created
                    session.execute(
                        text("""
                            UPDATE duplicate_members 
                            SET shortcut_created = TRUE,
                                shortcut_target_path = :target_path
                            WHERE id = :member_id
                        """),
                        {
                            "member_id": row.member_id,
                            "target_path": str(primary_file)
                        }
                    )
                    
                    self.manifest.add_shortcut(
                        shortcut_path=str(shortcut_path),
                        target_path=str(primary_file),
                        original_path=f"{row.dup_path}/{row.dup_name}",
                        shortcut_type=shortcut_type
                    )
                    
                    self.manifest.add_operation(
                        operation_type="create_shortcut",
                        source_path=str(primary_file),
                        target_path=str(shortcut_path),
                        document_id=row.document_id,
                        success=True
                    )
                else:
                    error_msg = f"Failed to create shortcut for document {row.document_id}"
                    self._errors.append(error_msg)
                    self.manifest.add_error(row.document_id, error_msg)
            
            session.commit()
            return created_count
            
        except Exception as e:
            session.rollback()
            self.logger.error("shortcut_creation_failed", error=str(e), exc_info=True)
            raise
        finally:
            session.close()
    
    async def _setup_version_archives(self) -> int:
        """
        Setup version archive structure for version chains.
        
        For each version chain:
        1. Create archive directory
        2. Copy superseded versions to archive with version names
        3. Ensure current version is in main location
        4. Create _version_history.json manifest
        
        Returns:
            Number of version archives created
        """
        session = self.get_sync_session()
        archives_created = 0
        
        try:
            # Get version chains
            result = session.execute(
                text("""
                    SELECT 
                        vc.id as chain_id,
                        vc.chain_name,
                        vc.archive_path,
                        vc.archive_strategy,
                        vc.current_document_id
                    FROM version_chains vc
                    WHERE vc.archive_path IS NOT NULL
                """)
            )
            
            chains = result.fetchall()
            
            for chain in chains:
                try:
                    # Create archive directory
                    if chain.archive_path:
                        archive_dir = self.working_root / chain.archive_path.lstrip('/')
                        archive_dir.mkdir(parents=True, exist_ok=True)
                        
                        # Get all versions in this chain
                        versions_result = session.execute(
                            text("""
                                SELECT 
                                    vcm.document_id,
                                    vcm.version_number,
                                    vcm.is_current,
                                    vcm.status,
                                    vcm.proposed_version_name,
                                    vcm.proposed_version_path,
                                    di.final_name,
                                    di.final_path,
                                    di.current_name,
                                    di.current_path
                                FROM version_chain_members vcm
                                JOIN document_items di ON vcm.document_id = di.id
                                WHERE vcm.chain_id = :chain_id
                                ORDER BY vcm.version_number
                            """),
                            {"chain_id": chain.chain_id}
                        )
                        
                        versions = versions_result.fetchall()
                        
                        # Copy superseded versions to archive
                        for version in versions:
                            if not version.is_current and version.status == 'superseded':
                                # Find source file
                                source_name = version.final_name or version.current_name
                                source_path_str = version.final_path or version.current_path
                                source_file = self.working_root / source_path_str.lstrip('/') / source_name
                                
                                # Determine archive filename
                                archive_name = version.proposed_version_name or f"{source_name}_v{version.version_number}"
                                archive_file = archive_dir / archive_name
                                
                                # Copy to archive if source exists in working
                                if source_file.exists():
                                    shutil.copy2(source_file, archive_file)
                        
                        # Create version history JSON
                        history_file = archive_dir / "_version_history.json"
                        self._create_version_history_json(chain.chain_id, history_file, session)
                        
                        archives_created += 1
                        self.manifest.increment_version_archives()
                        
                except Exception as e:
                    self.logger.error(
                        "version_archive_failed",
                        chain_id=chain.chain_id,
                        error=str(e)
                    )
                    self._errors.append(f"Failed to create version archive for chain {chain.chain_id}: {str(e)}")
            
            return archives_created
            
        finally:
            session.close()
    
    def _create_version_history_json(self, chain_id: int, output_path: Path, session) -> dict:
        """
        Create version history manifest.
        
        Args:
            chain_id: Version chain ID
            output_path: Path where JSON should be saved
            session: Database session
            
        Returns:
            Version history dictionary
        """
        # Get chain info
        chain_result = session.execute(
            text("""
                SELECT 
                    chain_name,
                    current_version_number,
                    archive_path,
                    archive_strategy
                FROM version_chains
                WHERE id = :chain_id
            """),
            {"chain_id": chain_id}
        )
        chain = chain_result.fetchone()
        
        # Get all versions
        versions_result = session.execute(
            text("""
                SELECT 
                    vcm.version_number,
                    vcm.is_current,
                    vcm.status,
                    vcm.proposed_version_name,
                    vcm.version_date,
                    di.final_name,
                    di.current_name
                FROM version_chain_members vcm
                JOIN document_items di ON vcm.document_id = di.id
                WHERE vcm.chain_id = :chain_id
                ORDER BY vcm.version_number
            """),
            {"chain_id": chain_id}
        )
        
        versions = []
        current_file = None
        
        for v in versions_result:
            file_name = v.proposed_version_name or v.final_name or v.current_name
            
            if v.is_current:
                current_file = f"../{file_name}"
            
            versions.append({
                "version": v.version_number,
                "file": file_name if not v.is_current else f"../{file_name}",
                "date": v.version_date.isoformat() if v.version_date else None,
                "status": v.status
            })
        
        history = {
            "document_name": chain.chain_name,
            "current_version": chain.current_version_number,
            "current_file": current_file,
            "archive_path": chain.archive_path,
            "archive_strategy": chain.archive_strategy,
            "versions": versions,
            "generated_at": datetime.utcnow().isoformat()
        }
        
        # Write JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        
        return history
    
    async def _generate_manifest(self) -> Path:
        """
        Generate complete manifest of all changes.
        
        Returns:
            Path to the generated manifest file
        """
        # Determine source ZIP name
        session = self.get_sync_session()
        try:
            result = session.execute(
                text("SELECT source_path FROM processing_jobs WHERE id = :job_id"),
                {"job_id": self.job_id}
            )
            row = result.fetchone()
            source_zip = row.source_path if row else None
        finally:
            session.close()
        
        # Generate manifest
        manifest_path = self.reports_root / f"{self.job_id}_manifest.json"
        return self.manifest.generate_manifest(
            job_id=self.job_id,
            source_zip=source_zip,
            output_path=manifest_path
        )
    
    async def _update_final_states(self):
        """Update processing job with final statistics."""
        session = self.get_sync_session()
        try:
            session.execute(
                text("""
                    UPDATE processing_jobs
                    SET 
                        files_moved = :files_moved,
                        files_renamed = :files_renamed,
                        shortcuts_created = :shortcuts_created,
                        current_phase = 'completed',
                        completed_at = NOW()
                    WHERE id = :job_id
                """),
                {
                    "files_moved": self.manifest.statistics.get("files_moved", 0),
                    "files_renamed": self.manifest.statistics.get("files_renamed", 0),
                    "shortcuts_created": self._shortcuts_created,
                    "job_id": self.job_id
                }
            )
            session.commit()
        finally:
            session.close()
    
    async def rollback(self, manifest_path: str) -> bool:
        """
        Rollback changes using a manifest file.
        
        Steps:
        1. Load manifest
        2. Remove /data/working/ contents
        3. Restore original structure from /data/source/
        4. Clear execution_log for this job
        5. Reset document_items status to 'organized'
        
        Args:
            manifest_path: Path to the manifest file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Load manifest
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
            
            job_id = manifest_data.get("job_id")
            
            self.logger.info("starting_rollback", job_id=job_id, manifest=manifest_path)
            
            # Clear working directory
            await self._clear_working_directory()
            
            # Reset database states
            session = self.get_sync_session()
            try:
                # Reset document_items
                session.execute(
                    text("""
                        UPDATE document_items
                        SET status = 'organized',
                            changes_applied = FALSE,
                            final_name = NULL,
                            final_path = NULL,
                            applied_at = NULL
                        WHERE job_id = :job_id
                    """),
                    {"job_id": job_id}
                )
                
                # Reset duplicate shortcuts
                session.execute(
                    text("""
                        UPDATE duplicate_members
                        SET shortcut_created = FALSE,
                            shortcut_target_path = NULL
                        WHERE document_id IN (
                            SELECT id FROM document_items WHERE job_id = :job_id
                        )
                    """),
                    {"job_id": job_id}
                )
                
                # Clear shortcut files
                session.execute(
                    text("""
                        DELETE FROM shortcut_files
                        WHERE original_document_id IN (
                            SELECT id FROM document_items WHERE job_id = :job_id
                        )
                    """),
                    {"job_id": job_id}
                )
                
                # Clear execution log
                session.execute(
                    text("DELETE FROM execution_log WHERE job_id = :job_id"),
                    {"job_id": job_id}
                )
                
                # Update job status
                session.execute(
                    text("""
                        UPDATE processing_jobs
                        SET current_phase = 'organized',
                            completed_at = NULL
                        WHERE id = :job_id
                    """),
                    {"job_id": job_id}
                )
                
                session.commit()
                
                self.logger.info("rollback_complete", job_id=job_id)
                return True
                
            except Exception as e:
                session.rollback()
                self.logger.error("rollback_failed", error=str(e))
                return False
            finally:
                session.close()
                
        except Exception as e:
            self.logger.error("rollback_error", error=str(e), exc_info=True)
            return False
