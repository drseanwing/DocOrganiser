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
# from src.agents.version_agent import VersionAgent  # TODO: Implement
# from src.agents.organize_agent import OrganizeAgent  # TODO: Implement
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
            
            # Phase 4: Deduplicate
            if "dedup" not in skip_phases:
                await self._update_job_status(ProcessingPhase.DEDUPLICATING)
                dedup_result = await self._run_deduplication()
                if not dedup_result.success:
                    logger.warning("dedup_issues", error=dedup_result.error)
            
            # Phase 5: Version control
            if "version" not in skip_phases:
                await self._update_job_status(ProcessingPhase.VERSIONING)
                # TODO: Implement version agent
                logger.info("version_detection_placeholder")
            
            # Phase 6: Organization planning
            if "organize" not in skip_phases:
                await self._update_job_status(ProcessingPhase.ORGANIZING)
                # TODO: Implement organization agent
                logger.info("organization_planning_placeholder")
            
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
            
            return {
                "status": "completed",
                "job_id": self.job_id,
                "output_path": output_path
            }
            
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
        
        # Clear existing source directory
        if source_dir.exists():
            shutil.rmtree(source_dir)
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
        """Execute planned file changes."""
        logger.info("executing_changes_placeholder")
        # TODO: Implement file operations
        # - Create directory structure
        # - Move/rename files
        # - Create shortcuts
        # - Generate version folders
    
    async def _package_output(self) -> str:
        """Package working directory into output ZIP."""
        output_dir = Path(self.settings.data_output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"organized_{timestamp}.zip"
        
        # For now, just package the source (since we haven't moved anything)
        source_dir = Path(self.settings.data_source_path)
        
        logger.info("packaging_output", source=str(source_dir), dest=str(output_path))
        
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in source_dir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(source_dir)
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
        # Simple file watcher
        input_dir = Path(get_settings().data_input_path)
        while True:
            for zip_file in input_dir.glob("*.zip"):
                logger.info("found_zip", path=str(zip_file))
                organizer = DocumentOrganizer()
                try:
                    result = await organizer.process_zip(str(zip_file))
                    logger.info("processing_result", **result)
                    # Move processed ZIP
                    zip_file.rename(zip_file.with_suffix('.zip.processed'))
                except Exception as e:
                    logger.error("processing_error", error=str(e))
                    zip_file.rename(zip_file.with_suffix('.zip.error'))
            
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
