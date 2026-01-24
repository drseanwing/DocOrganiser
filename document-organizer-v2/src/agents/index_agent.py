"""
Index Agent - File Discovery and Content Hashing.

Phase 1 of the processing pipeline:
1. Walk the source directory tree
2. Calculate SHA256 hash for each file
3. Extract metadata (size, dates, MIME type)
4. Extract text content for supported file types
5. Generate content summaries using Ollama
6. Store everything in document_items table
"""

import hashlib
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional
import mimetypes

from sqlalchemy import text

from src.config import ProcessingPhase
from src.agents.base_agent import BaseAgent, AgentResult
from src.services.ollama_service import OllamaService
from src.extractors import get_extractor


class IndexAgent(BaseAgent):
    """
    Agent responsible for indexing all files in the source directory.
    
    Creates a complete inventory with:
    - File metadata (path, size, dates, type)
    - Content hash (SHA256)
    - Extracted text (where possible)
    - AI-generated summary
    """
    
    AGENT_NAME = "index_agent"
    AGENT_PHASE = ProcessingPhase.INDEXING
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ollama_service = OllamaService(self.settings)
        self._files_indexed = 0
        self._files_skipped = 0
        self._errors = []
    
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """Validate that source directory exists and has files."""
        source_path = Path(self.settings.data_source_path)
        
        if not source_path.exists():
            return False, f"Source directory does not exist: {source_path}"
        
        if not source_path.is_dir():
            return False, f"Source path is not a directory: {source_path}"
        
        # Check for at least one file
        has_files = any(source_path.rglob("*"))
        if not has_files:
            return False, f"Source directory is empty: {source_path}"
        
        # Verify Ollama is accessible
        if not await self.ollama_service.health_check():
            return False, f"Ollama service not available at {self.settings.ollama_host}"
        
        return True, ""
    
    async def run(self, skip_existing: bool = False, force_rehash: bool = False) -> AgentResult:
        """
        Index all files in the source directory.
        
        Args:
            skip_existing: Skip files already in database
            force_rehash: Recalculate hash even if file exists in DB
            
        Returns:
            AgentResult with indexing statistics
        """
        self.logger.info("index_agent_starting", 
                         source_path=self.settings.data_source_path,
                         skip_existing=skip_existing)
        
        # Validate prerequisites
        valid, error = await self.validate_prerequisites()
        if not valid:
            return AgentResult(success=False, error=error)
        
        self.update_job_phase(ProcessingPhase.INDEXING)
        
        # Count total files first
        source_path = Path(self.settings.data_source_path)
        all_files = list(self._walk_files(source_path))
        self.start_processing(len(all_files))
        
        self.logger.info("files_discovered", count=len(all_files))
        
        # Process files in batches
        batch_size = self.settings.batch_size
        
        for batch_num, batch_start in enumerate(range(0, len(all_files), batch_size)):
            batch = all_files[batch_start:batch_start + batch_size]
            self.logger.debug("processing_batch", 
                            batch_num=batch_num + 1, 
                            batch_size=len(batch))
            
            # Process batch concurrently (limited concurrency)
            semaphore = asyncio.Semaphore(5)  # Max 5 concurrent
            tasks = [
                self._process_file_with_semaphore(file_path, semaphore, skip_existing, force_rehash)
                for file_path in batch
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update job progress
            progress_pct = int((self.processed_items / self.total_items) * 100)
            self.update_job_phase(ProcessingPhase.INDEXING, progress_pct)
        
        # Generate final result
        result = AgentResult(
            success=True,
            processed_count=self._files_indexed,
            skipped_count=self._files_skipped,
            error_count=len(self._errors),
            duration_seconds=self.get_elapsed_seconds(),
            metadata={
                "total_files": len(all_files),
                "errors": self._errors[:10]  # First 10 errors
            }
        )
        
        self.logger.info("index_agent_complete", **result.to_dict())
        return result
    
    def _walk_files(self, root: Path) -> list[Path]:
        """
        Walk directory tree and yield file paths.
        
        Respects configuration for supported extensions and max file size.
        """
        files = []
        supported_ext = set(self.settings.supported_extensions)
        
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            
            # Skip hidden files and system files
            if path.name.startswith('.') or path.name.startswith('~'):
                continue
            
            # Check extension
            ext = path.suffix.lower().lstrip('.')
            if supported_ext and ext not in supported_ext:
                self.logger.debug("skipping_unsupported_extension", 
                                 path=str(path), extension=ext)
                continue
            
            # Check file size
            try:
                size = path.stat().st_size
                if size > self.settings.max_file_size_bytes:
                    self.logger.debug("skipping_large_file", 
                                     path=str(path), 
                                     size_mb=size / (1024*1024))
                    continue
            except OSError:
                continue
            
            files.append(path)
        
        return files
    
    async def _process_file_with_semaphore(
        self, 
        file_path: Path, 
        semaphore: asyncio.Semaphore,
        skip_existing: bool,
        force_rehash: bool
    ):
        """Process a single file with concurrency limiting."""
        async with semaphore:
            await self._process_file(file_path, skip_existing, force_rehash)
    
    async def _process_file(
        self, 
        file_path: Path,
        skip_existing: bool,
        force_rehash: bool
    ):
        """
        Process a single file: hash, extract metadata, summarize.
        
        Args:
            file_path: Path to the file
            skip_existing: Skip if already in database
            force_rehash: Recalculate hash even for existing files
        """
        relative_path = file_path.relative_to(self.settings.data_source_path)
        self.update_progress(str(relative_path))
        
        try:
            # Calculate content hash
            content_hash = self._calculate_hash(file_path)
            
            # Check if exists in DB
            if skip_existing and not force_rehash:
                exists = self._check_exists_in_db(content_hash)
                if exists:
                    self._files_skipped += 1
                    return
            
            # Get file metadata
            stat = file_path.stat()
            mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            
            # Extract text content
            extracted_text = await self._extract_text(file_path)
            
            # Generate summary with Ollama (if text extracted)
            summary = None
            document_type = None
            key_topics = []
            
            if extracted_text and len(extracted_text.strip()) > 50:
                summary_result = await self._generate_summary(
                    file_path.name, 
                    str(relative_path), 
                    extracted_text
                )
                if summary_result:
                    summary = summary_result.get("summary")
                    document_type = summary_result.get("document_type")
                    key_topics = summary_result.get("key_topics", [])
            
            # Insert/update in database
            await self._upsert_document(
                file_path=file_path,
                relative_path=str(relative_path),
                content_hash=content_hash,
                file_size=stat.st_size,
                mime_type=mime_type,
                created_at=datetime.fromtimestamp(stat.st_ctime),
                modified_at=datetime.fromtimestamp(stat.st_mtime),
                extracted_text=extracted_text,
                summary=summary,
                document_type=document_type,
                key_topics=key_topics
            )
            
            self._files_indexed += 1
            
            self.log_to_db(
                action="index_file",
                details={
                    "path": str(relative_path),
                    "hash": content_hash[:16],
                    "size": stat.st_size,
                    "has_summary": summary is not None
                }
            )
            
        except Exception as e:
            self._errors.append({
                "file": str(relative_path),
                "error": str(e)
            })
            self.logger.error("file_processing_error", 
                            path=str(relative_path), 
                            error=str(e))
    
    def _calculate_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file content."""
        sha256 = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def _check_exists_in_db(self, content_hash: str) -> bool:
        """Check if a file with this hash already exists in the database."""
        session = self.get_sync_session()
        try:
            result = session.execute(
                text("SELECT 1 FROM document_items WHERE content_hash = :hash LIMIT 1"),
                {"hash": content_hash}
            )
            return result.fetchone() is not None
        finally:
            session.close()
    
    async def _extract_text(self, file_path: Path) -> Optional[str]:
        """Extract text content from file using appropriate extractor."""
        ext = file_path.suffix.lower().lstrip('.')
        
        extractor = get_extractor(ext)
        if extractor is None:
            return None
        
        try:
            text = await extractor.extract(file_path)
            # Truncate very long text
            if text and len(text) > 50000:
                text = text[:50000] + "\n[TRUNCATED...]"
            return text
        except Exception as e:
            self.logger.warning("text_extraction_failed", 
                              path=str(file_path), 
                              error=str(e))
            return None
    
    async def _generate_summary(
        self, 
        filename: str, 
        filepath: str, 
        content: str
    ) -> Optional[dict]:
        """Generate content summary using Ollama."""
        prompt = f"""Analyze this document for organization purposes.

DOCUMENT:
Filename: {filename}
Path: {filepath}

Content (first 10000 chars):
{content[:10000]}

Provide analysis in this exact JSON format:
{{
  "summary": "2-3 sentence summary of the document content and purpose",
  "document_type": "one of: meeting_notes, policy, report, template, correspondence, presentation, data, reference, draft, archive, other",
  "key_topics": ["topic1", "topic2", "topic3"]
}}

Respond ONLY with the JSON, no other text."""

        try:
            response = await self.ollama_service.generate(prompt)
            if response:
                # Try to parse JSON from response
                import json
                import re
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    return json.loads(json_match.group())
        except Exception as e:
            self.logger.warning("summary_generation_failed", error=str(e))
        
        return None
    
    async def _upsert_document(
        self,
        file_path: Path,
        relative_path: str,
        content_hash: str,
        file_size: int,
        mime_type: str,
        created_at: datetime,
        modified_at: datetime,
        extracted_text: Optional[str],
        summary: Optional[str],
        document_type: Optional[str],
        key_topics: list[str]
    ):
        """Insert or update document in database."""
        import json
        session = self.get_sync_session()
        
        try:
            # Generate a unique file_id from path (since we don't have OneDrive IDs)
            file_id = hashlib.md5(relative_path.encode()).hexdigest()
            
            session.execute(
                text("""
                    INSERT INTO document_items (
                        file_id, current_name, current_path, current_extension,
                        file_size_bytes, mime_type, content_hash,
                        source_created_at, source_modified_at,
                        content_summary, document_type, key_topics,
                        status, crawled_at, processed_at, ollama_model
                    ) VALUES (
                        :file_id, :name, :path, :ext,
                        :size, :mime, :hash,
                        :created, :modified,
                        :summary, :doc_type, :topics,
                        :status, NOW(), 
                        CASE WHEN :summary IS NOT NULL THEN NOW() ELSE NULL END,
                        CASE WHEN :summary IS NOT NULL THEN :model ELSE NULL END
                    )
                    ON CONFLICT (file_id) DO UPDATE SET
                        current_name = EXCLUDED.current_name,
                        current_path = EXCLUDED.current_path,
                        file_size_bytes = EXCLUDED.file_size_bytes,
                        content_hash = EXCLUDED.content_hash,
                        source_modified_at = EXCLUDED.source_modified_at,
                        content_summary = COALESCE(EXCLUDED.content_summary, document_items.content_summary),
                        document_type = COALESCE(EXCLUDED.document_type, document_items.document_type),
                        key_topics = COALESCE(EXCLUDED.key_topics, document_items.key_topics),
                        status = CASE 
                            WHEN EXCLUDED.content_summary IS NOT NULL THEN 'processed'
                            ELSE 'discovered'
                        END,
                        crawled_at = NOW(),
                        processed_at = CASE WHEN EXCLUDED.content_summary IS NOT NULL THEN NOW() ELSE document_items.processed_at END
                """),
                {
                    "file_id": file_id,
                    "name": file_path.name,
                    "path": relative_path,
                    "ext": file_path.suffix.lower().lstrip('.'),
                    "size": file_size,
                    "mime": mime_type,
                    "hash": content_hash,
                    "created": created_at,
                    "modified": modified_at,
                    "summary": summary,
                    "doc_type": document_type,
                    "topics": key_topics if key_topics else None,
                    "status": "processed" if summary else "discovered",
                    "model": self.settings.ollama_model
                }
            )
            session.commit()
            
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
