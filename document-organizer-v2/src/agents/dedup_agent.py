"""
Duplicate Detection Agent - Find and Handle Duplicate Files.

Phase 2 of the processing pipeline:
1. Group files by content hash
2. For each duplicate group, analyze paths/dates/names
3. Use LLM to decide: PRIMARY, SHORTCUT, KEEP_BOTH, DELETE
4. Record decisions for execution phase
"""

import asyncio
from datetime import datetime
from typing import Optional
from pathlib import Path

from sqlalchemy import text

from src.config import ProcessingPhase, DuplicateAction, get_settings
from src.agents.base_agent import BaseAgent, AgentResult
from src.services.ollama_service import OllamaService


class DedupAgent(BaseAgent):
    """
    Agent responsible for detecting and handling duplicate files.
    
    Duplicates are files with identical content (same SHA256 hash).
    For each group of duplicates, determines:
    - Which file should be the PRIMARY (authoritative copy)
    - Which should become SHORTCUTS pointing to primary
    - Which should be KEPT as separate copies (intentional duplicates)
    - Which should be DELETED (rare, requires explicit approval)
    """
    
    AGENT_NAME = "dedup_agent"
    AGENT_PHASE = ProcessingPhase.DEDUPLICATING
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ollama_service = OllamaService(self.settings)
        self._groups_processed = 0
        self._shortcuts_planned = 0
        self._errors = []
    
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """Validate that indexing has been completed."""
        session = self.get_sync_session()
        try:
            # Check for indexed documents
            result = session.execute(
                text("SELECT COUNT(*) FROM document_items WHERE content_hash IS NOT NULL")
            )
            count = result.scalar()
            
            if count == 0:
                return False, "No indexed documents found. Run Index Agent first."
            
            return True, ""
        finally:
            session.close()
    
    async def run(self, min_group_size: int = 2) -> AgentResult:
        """
        Find and process duplicate file groups.
        
        Args:
            min_group_size: Minimum files to consider a duplicate group
            
        Returns:
            AgentResult with deduplication statistics
        """
        self.logger.info("dedup_agent_starting")
        
        # Validate prerequisites
        valid, error = await self.validate_prerequisites()
        if not valid:
            return AgentResult(success=False, error=error)
        
        self.update_job_phase(ProcessingPhase.DEDUPLICATING)
        
        # Find duplicate groups
        duplicate_groups = await self._find_duplicate_groups(min_group_size)
        self.start_processing(len(duplicate_groups))
        
        self.logger.info("duplicate_groups_found", count=len(duplicate_groups))
        
        if not duplicate_groups:
            return AgentResult(
                success=True,
                processed_count=0,
                metadata={"message": "No duplicates found"}
            )
        
        # Process each group
        for group in duplicate_groups:
            await self._process_duplicate_group(group)
            self._groups_processed += 1
            
            progress_pct = int((self._groups_processed / len(duplicate_groups)) * 100)
            self.update_job_phase(ProcessingPhase.DEDUPLICATING, progress_pct)
        
        result = AgentResult(
            success=True,
            processed_count=self._groups_processed,
            duration_seconds=self.get_elapsed_seconds(),
            metadata={
                "duplicate_groups": len(duplicate_groups),
                "shortcuts_planned": self._shortcuts_planned,
                "errors": self._errors[:10]
            }
        )
        
        self.logger.info("dedup_agent_complete", **result.to_dict())
        return result
    
    async def _find_duplicate_groups(self, min_group_size: int) -> list[dict]:
        """
        Find groups of files with identical content hashes.
        
        Returns list of groups, each containing:
        - content_hash
        - files: list of file records
        """
        session = self.get_sync_session()
        try:
            # Find hashes with multiple files
            result = session.execute(
                text("""
                    SELECT 
                        content_hash,
                        COUNT(*) as file_count,
                        SUM(file_size_bytes) as total_size,
                        array_agg(id) as document_ids
                    FROM document_items
                    WHERE content_hash IS NOT NULL
                      AND is_deleted = FALSE
                      AND file_size_bytes >= :min_size
                    GROUP BY content_hash
                    HAVING COUNT(*) >= :min_count
                    ORDER BY SUM(file_size_bytes) DESC
                """),
                {
                    "min_count": min_group_size,
                    "min_size": self.settings.min_duplicate_size_bytes
                }
            )
            
            groups = []
            for row in result:
                # Fetch full file details for each group
                files_result = session.execute(
                    text("""
                        SELECT id, file_id, current_name, current_path, 
                               file_size_bytes, source_created_at, source_modified_at,
                               content_summary
                        FROM document_items
                        WHERE content_hash = :hash
                        ORDER BY source_modified_at DESC NULLS LAST
                    """),
                    {"hash": row.content_hash}
                )
                
                files = [dict(r._mapping) for r in files_result]
                
                groups.append({
                    "content_hash": row.content_hash,
                    "file_count": row.file_count,
                    "total_size": row.total_size,
                    "files": files
                })
            
            return groups
            
        finally:
            session.close()
    
    async def _process_duplicate_group(self, group: dict):
        """
        Process a single group of duplicate files.
        
        Determines primary file and actions for others.
        """
        content_hash = group["content_hash"]
        files = group["files"]
        
        self.update_progress(f"Hash: {content_hash[:16]}...")
        
        try:
            # Use heuristics first
            primary_id, decisions = await self._analyze_duplicates(files)
            
            # If heuristics are uncertain, ask LLM
            if self._needs_llm_decision(decisions):
                llm_decisions = await self._get_llm_decision(files, group)
                if llm_decisions:
                    primary_id = llm_decisions.get("primary_id", primary_id)
                    decisions = llm_decisions.get("decisions", decisions)
            
            # Store decisions in database
            await self._store_decisions(content_hash, primary_id, decisions, files)
            
            # Count shortcuts
            self._shortcuts_planned += sum(
                1 for d in decisions.values() 
                if d["action"] == DuplicateAction.SHORTCUT.value
            )
            
            self.log_to_db(
                action="process_duplicate_group",
                details={
                    "hash": content_hash[:16],
                    "file_count": len(files),
                    "primary_id": primary_id,
                    "shortcuts": self._shortcuts_planned
                }
            )
            
        except Exception as e:
            self._errors.append({
                "hash": content_hash[:16],
                "error": str(e)
            })
            self.logger.error("duplicate_group_error", 
                            hash=content_hash[:16], 
                            error=str(e))
    
    async def _analyze_duplicates(self, files: list[dict]) -> tuple[int, dict]:
        """
        Analyze duplicate files using heuristics to determine primary and actions.
        
        Heuristics:
        1. File in more "canonical" path (shorter, cleaner) = likely primary
        2. Most recently modified = likely current
        3. Files in "backup", "archive", "old", "copy" paths = likely secondary
        
        Returns:
            Tuple of (primary_document_id, {doc_id: {action, reasoning}})
        """
        # Score each file
        scores = {}
        for f in files:
            score = 0
            path_lower = f["current_path"].lower()
            name_lower = f["current_name"].lower()
            
            # Penalty for backup/archive indicators
            if any(x in path_lower for x in ["backup", "archive", "old", "copy", "temp", "draft"]):
                score -= 20
            if any(x in name_lower for x in ["backup", "copy", "_old", " copy", "(1)", "(2)"]):
                score -= 15
            
            # Bonus for clean paths
            path_depth = path_lower.count('/')
            score -= path_depth * 2  # Prefer shallower paths
            
            # Bonus for recent modification
            if f["source_modified_at"]:
                # More recent = higher score
                days_old = (datetime.utcnow() - f["source_modified_at"]).days
                score -= min(days_old, 365) / 10  # Cap at 1 year
            
            # Bonus for having a summary (indicates processed/important)
            if f["content_summary"]:
                score += 5
            
            scores[f["id"]] = score
        
        # Primary is highest score
        primary_id = max(scores, key=scores.get)
        
        # Build decisions
        decisions = {}
        for f in files:
            doc_id = f["id"]
            if doc_id == primary_id:
                decisions[doc_id] = {
                    "action": DuplicateAction.KEEP_PRIMARY.value,
                    "reasoning": "Selected as primary based on path and recency"
                }
            else:
                # Default to shortcut unless auto-approve is disabled
                if self.settings.auto_approve_shortcuts:
                    action = DuplicateAction.SHORTCUT.value
                    reasoning = "Auto-approved for shortcut (exact duplicate)"
                else:
                    action = DuplicateAction.SHORTCUT.value  # Suggested, needs review
                    reasoning = "Suggested for shortcut - review recommended"
                
                decisions[doc_id] = {
                    "action": action,
                    "reasoning": reasoning
                }
        
        return primary_id, decisions
    
    def _needs_llm_decision(self, decisions: dict) -> bool:
        """Determine if we need LLM input for this group."""
        # If auto-approve is enabled, no LLM needed
        if self.settings.auto_approve_shortcuts:
            return False
        
        # If more than 3 duplicates, might want LLM to analyze
        if len(decisions) > 3:
            return True
        
        return False
    
    async def _get_llm_decision(self, files: list[dict], group: dict) -> Optional[dict]:
        """
        Ask LLM to decide how to handle duplicate files.
        
        Returns dict with primary_id and decisions, or None on failure.
        """
        # Build prompt
        files_desc = "\n".join([
            f"- ID {f['id']}: {f['current_path']} (modified: {f['source_modified_at']}, size: {f['file_size_bytes']} bytes)"
            for f in files
        ])
        
        prompt = f"""These files are byte-identical duplicates (same content, hash: {group['content_hash'][:16]}...):

{files_desc}

Analyze the paths and dates to determine:
1. Which file should be PRIMARY (the authoritative copy)?
2. For each other file, should it be:
   - SHORTCUT: Replace with a shortcut/link to the primary
   - KEEP_BOTH: Keep as a separate copy (e.g., intentionally distributed template)
   - DELETE: Remove entirely (only if clearly obsolete backup)

Consider:
- Files in "backup", "archive", "old" folders are usually secondary
- Files with cleaner paths are usually authoritative
- Most recently modified is usually current
- Some duplicates are intentional (templates in multiple projects)

Respond in this exact JSON format:
{{
  "primary_id": <id of primary file>,
  "reasoning": "Brief explanation of why this is primary",
  "decisions": {{
    "<id>": {{"action": "SHORTCUT|KEEP_BOTH|DELETE", "reasoning": "why"}},
    ...
  }}
}}

Respond ONLY with JSON."""

        try:
            response = await self.ollama_service.generate(prompt)
            if response:
                import json
                import re
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    result = json.loads(json_match.group())
                    return {
                        "primary_id": result.get("primary_id"),
                        "decisions": {
                            int(k): {
                                "action": v["action"].lower(),
                                "reasoning": v.get("reasoning", "")
                            }
                            for k, v in result.get("decisions", {}).items()
                        }
                    }
        except Exception as e:
            self.logger.warning("llm_decision_failed", error=str(e))
        
        return None
    
    async def _store_decisions(
        self, 
        content_hash: str, 
        primary_id: int, 
        decisions: dict, 
        files: list[dict]
    ):
        """Store duplicate group and member decisions in database."""
        session = self.get_sync_session()
        
        try:
            # Create duplicate group
            result = session.execute(
                text("""
                    INSERT INTO duplicate_groups (content_hash, file_count, total_size_bytes, primary_document_id, decided_at, decided_by)
                    VALUES (:hash, :count, :size, :primary, NOW(), 'auto')
                    ON CONFLICT (content_hash) DO UPDATE SET
                        primary_document_id = EXCLUDED.primary_document_id,
                        decided_at = NOW()
                    RETURNING id
                """),
                {
                    "hash": content_hash,
                    "count": len(files),
                    "size": sum(f["file_size_bytes"] for f in files),
                    "primary": primary_id
                }
            )
            group_id = result.scalar()
            
            # Create member records
            for doc_id, decision in decisions.items():
                session.execute(
                    text("""
                        INSERT INTO duplicate_members (group_id, document_id, is_primary, action, action_reasoning)
                        VALUES (:group_id, :doc_id, :is_primary, :action, :reasoning)
                        ON CONFLICT (group_id, document_id) DO UPDATE SET
                            is_primary = EXCLUDED.is_primary,
                            action = EXCLUDED.action,
                            action_reasoning = EXCLUDED.action_reasoning
                    """),
                    {
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "is_primary": doc_id == primary_id,
                        "action": decision["action"],
                        "reasoning": decision["reasoning"]
                    }
                )
            
            session.commit()
            
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
