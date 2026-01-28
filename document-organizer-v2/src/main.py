"""
Document Organizer v2 - Main Orchestrator.

Coordinates the processing pipeline:
1. Extract source ZIP
2. Run Index Agent
3. Run Dedup Agent
4. Run Version Agent
5. Run Organization Agent
6. Execute changes (if approved)
7. Package output
"""

import asyncio
import argparse
import os
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional
import json

import structlog
from sqlalchemy import create_engine, text

from src.config import Settings, get_settings, ProcessingPhase
from src.agents.index_agent import IndexAgent
from src.agents.dedup_agent import DedupAgent
from src.agents.version_agent import VersionAgent
from src.agents.organize_agent import OrganizeAgent
from src.execution.execution_engine import ExecutionEngine


# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger("orchestrator")


class DocumentOrganizer:
    """
    Main orchestrator for the document organization pipeline.
    
    Manages the complete workflow from ZIP extraction to final packaging.
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.job_id: Optional[str] = None
        self._engine = None
    
    @property
    def engine(self):
        """Lazy-load database engine."""
        if self._engine is None:
            self._engine = create_engine(self.settings.database_url)
        return self._engine
    
    async def process_zip(
        self, 
        zip_path: str, 
        job_id: Optional[str] = None,
        skip_phases: Optional[list[str]] = None
    ) -> dict:
        """
        Process a ZIP file through the complete pipeline.
        
        Args:
            zip_path: Path to input ZIP file
            job_id: Optional job ID (will be created if not provided)
            skip_phases: List of phases to skip (for resuming)
            
        Returns:
            Processing result dictionary
        """
        skip_phases = skip_phases or []
        
        logger.info("starting_processing", zip_path=zip_path)
        
        # Create or load job
        self.job_id = job_id or await self._create_job(zip_path)
        
        try:
            # Phase 1: Extract ZIP
            if "extract" not in skip_phases:
                await self._update_job_status(ProcessingPhase.EXTRACTING)
                await self._extract_zip(zip_path)
            
            # Phase 2: Index files
            if "index" not in skip_phases:
                await self._update_job_status(ProcessingPhase.INDEXING)
                index_result = await self._run_indexing()
                if not index_result.success:
                    raise Exception(f"Indexing failed: {index_result.error}")
            
            # Phase 3: Summarize content
            if "summarize" not in skip_phases:
                await self._update_job_status(ProcessingPhase.SUMMARIZING)
                # Summarization happens in Index Agent
            
            # Track phase issues for final reporting
            phase_issues = []
            
            # Phase 4: Deduplicate
            if "dedup" not in skip_phases:
                await self._update_job_status(ProcessingPhase.DEDUPLICATING)
                dedup_result = await self._run_deduplication()
                if not dedup_result.success:
                    logger.warning("dedup_issues", error=dedup_result.error)
                    phase_issues.append(("deduplication", dedup_result.error))
            
            # Phase 5: Version control
            if "version" not in skip_phases:
                await self._update_job_status(ProcessingPhase.VERSIONING)
                version_result = await self._run_versioning()
                if not version_result.success:
                    logger.warning("version_issues", error=version_result.error)
                    phase_issues.append(("versioning", version_result.error))
            
            # Phase 6: Organization planning
            if "organize" not in skip_phases:
                await self._update_job_status(ProcessingPhase.ORGANIZING)
                organize_result = await self._run_organization()
                if not organize_result.success:
                    logger.warning("organize_issues", error=organize_result.error)
                    phase_issues.append(("organization", organize_result.error))
            
            # Phase 7: Review required?
            if self.settings.review_required:
                await self._update_job_status(ProcessingPhase.REVIEW_REQUIRED)
                await self._generate_review_report()
                logger.info("review_required", 
                           message="Processing paused for review. Approve to continue.")
                return {
                    "status": "review_required",
                    "job_id": self.job_id,
                    "report_path": f"{self.settings.data_reports_path}/{self.job_id}_review.html"
                }
            
            # Phase 8: Execute changes
            if "execute" not in skip_phases and not self.settings.dry_run:
                await self._update_job_status(ProcessingPhase.EXECUTING)
                await self._execute_changes()
            
            # Phase 9: Package output
            if "package" not in skip_phases:
                await self._update_job_status(ProcessingPhase.PACKAGING)
                output_path = await self._package_output()
            
            # Complete
            await self._update_job_status(ProcessingPhase.COMPLETED)
            
            result = {
                "status": "completed",
                "job_id": self.job_id,
                "output_path": output_path
            }
            
            # Include any phase issues in the result
            if phase_issues:
                result["warnings"] = phase_issues
                logger.info("completed_with_warnings", 
                           phases_with_issues=[p[0] for p in phase_issues])
            
            return result
            
        except Exception as e:
            logger.error("processing_failed", error=str(e))
            await self._update_job_status(ProcessingPhase.FAILED, str(e))
            raise
    
    async def _create_job(self, zip_path: str) -> str:
        """Create a new processing job record."""
        import hashlib
        
        # Calculate ZIP hash
        sha256 = hashlib.sha256()
        with open(zip_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        zip_hash = sha256.hexdigest()
        
        zip_size = os.path.getsize(zip_path)
        
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO processing_jobs (
                        source_type, source_path, source_zip_path, source_zip_hash,
                        source_total_size, status, current_phase
                    ) VALUES (
                        'local', :path, :zip_path, :hash,
                        :size, 'pending', 'pending'
                    )
                    RETURNING id
                """),
                {
                    "path": zip_path,
                    "zip_path": zip_path,
                    "hash": zip_hash,
                    "size": zip_size
                }
            )
            conn.commit()
            job_id = str(result.scalar())
        
        logger.info("job_created", job_id=job_id)
        return job_id
    
    async def _update_job_status(
        self, 
        phase: ProcessingPhase, 
        error: Optional[str] = None
    ):
        """Update job status in database."""
        with self.engine.connect() as conn:
            conn.execute(
                text("""
                    UPDATE processing_jobs 
                    SET current_phase = :phase,
                        status = CASE 
                            WHEN :phase = 'failed' THEN 'failed'
                            WHEN :phase = 'completed' THEN 'completed'
                            WHEN :phase = 'review_required' THEN 'review_required'
                            ELSE 'processing'
                        END,
                        error_message = :error,
                        started_at = COALESCE(started_at, NOW())
                    WHERE id = :job_id
                """),
                {
                    "phase": phase.value,
                    "error": error,
                    "job_id": self.job_id
                }
            )
            conn.commit()
    
    async def _extract_zip(self, zip_path: str):
        """Extract ZIP to source directory."""
        source_dir = Path(self.settings.data_source_path)
        
        # Clear existing source directory contents (not the directory itself)
        # This is required because /data/source may be a Docker volume mount
        # that cannot be removed while mounted
        clear_failures = []
        if source_dir.exists():
            for item in source_dir.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except OSError as e:
                    logger.warning("failed_to_clear_item", 
                                   item=str(item), 
                                   error=str(e))
                    clear_failures.append(str(item))
        
        if clear_failures:
            logger.error("source_directory_not_fully_cleared",
                        failed_items=clear_failures,
                        message="Extraction may produce inconsistent results")
            raise OSError(f"Failed to clear {len(clear_failures)} item(s) from source directory")
        
        source_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("extracting_zip", zip_path=zip_path, dest=str(source_dir))
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(source_dir)
        
        # Count extracted files
        file_count = sum(1 for _ in source_dir.rglob('*') if _.is_file())
        logger.info("extraction_complete", file_count=file_count)
        
        # Update job with file count
        with self.engine.connect() as conn:
            conn.execute(
                text("UPDATE processing_jobs SET source_file_count = :count WHERE id = :job_id"),
                {"count": file_count, "job_id": self.job_id}
            )
            conn.commit()
    
    async def _run_indexing(self):
        """Run the Index Agent."""
        agent = IndexAgent(settings=self.settings, job_id=self.job_id)
        return await agent.run()
    
    async def _run_deduplication(self):
        """Run the Dedup Agent."""
        agent = DedupAgent(settings=self.settings, job_id=self.job_id)
        return await agent.run()
    
    async def _run_versioning(self):
        """Run the Version Agent."""
        agent = VersionAgent(settings=self.settings, job_id=self.job_id)
        return await agent.run()
    
    async def _run_organization(self):
        """Run the Organization Agent."""
        agent = OrganizeAgent(settings=self.settings, job_id=self.job_id)
        return await agent.run()
    
    async def _generate_review_report(self):
        """Generate HTML review report."""
        report_dir = Path(self.settings.data_reports_path)
        report_dir.mkdir(parents=True, exist_ok=True)
        
        # Gather statistics
        with self.engine.connect() as conn:
            stats = {}
            
            # Total files
            result = conn.execute(text("SELECT COUNT(*) FROM document_items WHERE is_deleted = FALSE"))
            stats["total_files"] = result.scalar()
            
            # Duplicates
            result = conn.execute(text("SELECT COUNT(*) FROM duplicate_groups"))
            stats["duplicate_groups"] = result.scalar()
            
            result = conn.execute(text(
                "SELECT COUNT(*) FROM duplicate_members WHERE action = 'shortcut'"
            ))
            stats["shortcuts_planned"] = result.scalar()
            
            # Pending changes
            result = conn.execute(text(
                "SELECT COUNT(*) FROM document_items WHERE has_name_change = TRUE OR has_path_change = TRUE"
            ))
            stats["pending_changes"] = result.scalar()
        
        # Generate simple HTML report
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Document Organization Review - {self.job_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .stat {{ background: #f5f5f5; padding: 20px; margin: 10px 0; border-radius: 8px; }}
        .stat h3 {{ margin: 0 0 10px 0; }}
        .warning {{ background: #fff3cd; }}
        .info {{ background: #d1ecf1; }}
    </style>
</head>
<body>
    <h1>Document Organization Review</h1>
    <p>Job ID: {self.job_id}</p>
    <p>Generated: {datetime.utcnow().isoformat()}</p>
    
    <div class="stat info">
        <h3>Total Files Indexed</h3>
        <p>{stats['total_files']} files</p>
    </div>
    
    <div class="stat {'warning' if stats['duplicate_groups'] > 0 else ''}">
        <h3>Duplicate Groups Found</h3>
        <p>{stats['duplicate_groups']} groups with identical files</p>
        <p>{stats['shortcuts_planned']} files will be replaced with shortcuts</p>
    </div>
    
    <div class="stat">
        <h3>Pending Changes</h3>
        <p>{stats['pending_changes']} files will be renamed or moved</p>
    </div>
    
    <h2>Approval</h2>
    <p>To approve and execute changes, run:</p>
    <pre>python -m src.main --approve --job-id {self.job_id}</pre>
</body>
</html>"""
        
        report_path = report_dir / f"{self.job_id}_review.html"
        with open(report_path, 'w') as f:
            f.write(html)
        
        logger.info("review_report_generated", path=str(report_path))
    
    async def _execute_changes(self):
        """Execute planned file changes using the Execution Engine."""
        logger.info("executing_changes", job_id=self.job_id)
        engine = ExecutionEngine(settings=self.settings, job_id=self.job_id)
        result = await engine.run(dry_run=self.settings.dry_run)
        if not result.success:
            raise Exception(f"Execution failed: {result.error}")
        logger.info("execution_complete", 
                   processed=result.processed_count,
                   duration=result.duration_seconds)
    
    async def _package_output(self) -> str:
        """Package working directory into output ZIP."""
        output_dir = Path(self.settings.data_output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"organized_{timestamp}.zip"
        
        # Package the working directory where execution put the reorganized files
        working_dir = Path(self.settings.data_working_path)
        source_dir = Path(self.settings.data_source_path)
        
        if not working_dir.exists() or not any(working_dir.iterdir()):
            # Fallback to source if no working directory - this is expected in dry-run mode
            # or when no changes were applied
            logger.warning("packaging_fallback_to_source",
                          reason="Working directory empty or missing",
                          working_dir=str(working_dir),
                          source_dir=str(source_dir))
            working_dir = source_dir
        
        logger.info("packaging_output", source=str(working_dir), dest=str(output_path))
        
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in working_dir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(working_dir)
                    zf.write(file_path, arcname)
        
        logger.info("packaging_complete", output=str(output_path))
        return str(output_path)


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Document Organizer v2")
    parser.add_argument("--zip", "-z", help="Input ZIP file to process")
    parser.add_argument("--job-id", "-j", help="Resume existing job")
    parser.add_argument("--approve", action="store_true", help="Approve and execute changes")
    parser.add_argument("--wait", action="store_true", help="Wait mode (for container)")
    parser.add_argument("--skip", nargs="*", help="Phases to skip", default=[])
    
    args = parser.parse_args()
    
    if args.wait:
        logger.info("waiting_for_input", 
                   message="Container running. Place ZIP in /data/input to process.")
        # Simple file watcher with tracking of processed/failed files
        input_dir = Path(get_settings().data_input_path)
        # Track files that couldn't be renamed to avoid infinite reprocessing
        skipped_files: set[str] = set()
        while True:
            for zip_file in input_dir.glob("*.zip"):
                # Skip files that we've already processed but couldn't rename
                if str(zip_file) in skipped_files:
                    continue
                    
                logger.info("found_zip", path=str(zip_file))
                organizer = DocumentOrganizer()
                try:
                    result = await organizer.process_zip(str(zip_file))
                    logger.info("processing_result", **result)
                    # Move processed ZIP
                    try:
                        zip_file.rename(zip_file.with_suffix('.zip.processed'))
                    except PermissionError:
                        logger.warning("cannot_rename_processed_file",
                                      path=str(zip_file),
                                      reason="Permission denied - file added to skip list")
                        skipped_files.add(str(zip_file))
                except Exception as e:
                    logger.error("processing_error", error=str(e))
                    try:
                        zip_file.rename(zip_file.with_suffix('.zip.error'))
                    except PermissionError:
                        logger.warning("cannot_rename_error_file",
                                      path=str(zip_file),
                                      reason="Permission denied - file added to skip list")
                        skipped_files.add(str(zip_file))
            
            await asyncio.sleep(10)
    
    elif args.zip:
        organizer = DocumentOrganizer()
        result = await organizer.process_zip(
            args.zip,
            job_id=args.job_id,
            skip_phases=args.skip
        )
        print(json.dumps(result, indent=2))
    
    elif args.approve and args.job_id:
        logger.info("approving_job", job_id=args.job_id)
        organizer = DocumentOrganizer()
        organizer.job_id = args.job_id
        await organizer._update_job_status(ProcessingPhase.APPROVED)
        await organizer._execute_changes()
        await organizer._package_output()
        await organizer._update_job_status(ProcessingPhase.COMPLETED)
    
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
