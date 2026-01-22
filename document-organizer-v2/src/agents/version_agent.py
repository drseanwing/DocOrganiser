"""
Version Control Agent - Document Version Detection and Management.

Phase 3 of the processing pipeline:
1. Detect version patterns in filenames (explicit markers)
2. Find similar-named files that might be versions
3. Confirm version relationships with Ollama LLM
4. Establish version chains with archive strategy
5. Plan version archiving structure
"""

import re
import asyncio
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Optional, List, Dict, Any, Tuple
from Levenshtein import ratio as levenshtein_ratio

from sqlalchemy import text

from src.config import ProcessingPhase, VersionArchiveStrategy, get_settings
from src.agents.base_agent import BaseAgent, AgentResult
from src.services.ollama_service import OllamaService


# Version detection patterns
VERSION_PATTERNS = [
    (r'_v(\d+)', 'version_number'),           # _v1, _v2
    (r'_rev(\d+)', 'revision_number'),        # _rev1, _rev2  
    (r'_version(\d+)', 'version_number'),     # _version1
    (r'\s*\((\d+)\)', 'copy_number'),         # (1), (2)
    (r'_(\d{4}-\d{2}-\d{2})', 'date'),        # _2024-01-15
    (r'_(\d{8})', 'date_compact'),            # _20240115
    (r'_(draft|final|approved|review|wip)', 'status'),
]

# Status priority for sorting (lower = older)
STATUS_PRIORITY = {
    'draft': 1,
    'wip': 2,
    'review': 3,
    'approved': 4,
    'final': 5
}


class VersionAgent(BaseAgent):
    """
    Agent responsible for detecting and managing document versions.
    
    Identifies files that are versions of the same document and:
    - Groups them into version chains
    - Determines which is the current version
    - Plans archive locations for superseded versions
    - Records all decisions for execution phase
    """
    
    AGENT_NAME = "version_agent"
    AGENT_PHASE = ProcessingPhase.VERSIONING
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ollama_service = OllamaService(self.settings)
        self._chains_created = 0
        self._versions_linked = 0
        self._explicit_groups = 0
        self._similar_groups = 0
        self._errors = []
    
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """Validate that indexing and deduplication are complete."""
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
    
    async def run(self, similarity_threshold: float = 0.7) -> AgentResult:
        """
        Main entry point for version detection and linking.
        
        Args:
            similarity_threshold: Minimum Levenshtein ratio for name similarity (0.0-1.0)
            
        Returns:
            AgentResult with version detection statistics
        """
        start_time = datetime.utcnow()
        self.logger.info("version_agent_starting", threshold=similarity_threshold)
        
        # Validate prerequisites
        valid, error = await self.validate_prerequisites()
        if not valid:
            return AgentResult(success=False, error=error)
        
        self.update_job_phase(ProcessingPhase.VERSIONING)
        
        try:
            # Step 1: Find explicit version groups
            self.logger.info("finding_explicit_versions")
            explicit_groups = await self._find_explicit_versions()
            self._explicit_groups = len(explicit_groups)
            self.logger.info("explicit_groups_found", count=self._explicit_groups)
            
            # Step 2: Find similar name groups (potential implicit versions)
            self.logger.info("finding_similar_names", threshold=similarity_threshold)
            similar_groups = await self._find_similar_names(similarity_threshold)
            self._similar_groups = len(similar_groups)
            self.logger.info("similar_groups_found", count=self._similar_groups)
            
            # Combine all groups
            all_groups = explicit_groups + similar_groups
            self.start_processing(len(all_groups))
            
            if not all_groups:
                duration = (datetime.utcnow() - start_time).total_seconds()
                return AgentResult(
                    success=True,
                    processed_count=0,
                    duration_seconds=duration,
                    metadata={
                        "version_chains": 0,
                        "versions_linked": 0,
                        "explicit_groups": 0,
                        "similar_groups": 0,
                        "message": "No version groups found"
                    }
                )
            
            # Step 3: Process each group
            for group in all_groups:
                await self._process_version_group(group)
                self.update_progress(
                    f"Processing group: {group['base_name']}", 
                    increment=1
                )
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            self.logger.info(
                "version_agent_completed",
                chains_created=self._chains_created,
                versions_linked=self._versions_linked,
                explicit_groups=self._explicit_groups,
                similar_groups=self._similar_groups,
                duration=duration
            )
            
            return AgentResult(
                success=True,
                processed_count=self._chains_created,
                duration_seconds=duration,
                metadata={
                    "version_chains": self._chains_created,
                    "versions_linked": self._versions_linked,
                    "explicit_groups": self._explicit_groups,
                    "similar_groups": self._similar_groups,
                    "errors": self._errors
                }
            )
            
        except Exception as e:
            self.logger.error("version_agent_error", error=str(e))
            duration = (datetime.utcnow() - start_time).total_seconds()
            return AgentResult(
                success=False,
                error=str(e),
                duration_seconds=duration
            )
    
    def _extract_version_info(self, filename: str) -> Tuple[str, Optional[Dict]]:
        """
        Extract version marker from filename.
        
        Args:
            filename: Filename without extension
            
        Returns:
            Tuple of (base_name_without_marker, version_info_dict or None)
            
        Example:
            "Budget_v2" → ("Budget", {"type": "version_number", "value": "2"})
            "Report_2024-01-15" → ("Report", {"type": "date", "value": "2024-01-15"})
        """
        for pattern, version_type in VERSION_PATTERNS:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                # Extract the base name by removing the matched pattern
                base_name = re.sub(pattern, '', filename, flags=re.IGNORECASE).strip('_- ')
                version_info = {
                    "type": version_type,
                    "value": match.group(1),
                    "marker": match.group(0)
                }
                return base_name, version_info
        
        return filename, None
    
    async def _find_explicit_versions(self) -> List[Dict]:
        """
        Find files with explicit version markers, grouped by base name + directory.
        
        Returns:
            List of version groups with their files
        """
        session = self.get_sync_session()
        try:
            # Get all files that are not marked as shortcuts or archived versions
            result = session.execute(
                text("""
                    SELECT d.id, d.current_name, d.current_path, d.current_extension,
                           d.content_hash, d.source_modified_at, d.content_summary
                    FROM document_items d
                    LEFT JOIN duplicate_members dm ON d.id = dm.document_id AND dm.action = 'shortcut'
                    LEFT JOIN version_chain_members vcm ON d.id = vcm.document_id
                    WHERE d.content_hash IS NOT NULL
                      AND d.is_deleted = FALSE
                      AND dm.id IS NULL
                      AND vcm.id IS NULL
                    ORDER BY d.current_path, d.current_name
                """)
            )
            files = [dict(row._mapping) for row in result]
            
            # Group files by base name + directory + extension
            groups = defaultdict(list)
            
            for file in files:
                # Remove extension from name
                name_without_ext = Path(file['current_name']).stem
                base_name, version_info = self._extract_version_info(name_without_ext)
                
                # Only include files with version markers
                if version_info:
                    directory = str(Path(file['current_path']).parent)
                    extension = file['current_extension']
                    group_key = (base_name, directory, extension)
                    
                    file['version_info'] = version_info
                    file['base_name'] = base_name
                    groups[group_key].append(file)
            
            # Convert to list format, filtering out single-file groups
            result_groups = []
            for (base_name, directory, extension), files in groups.items():
                if len(files) >= 2:  # Only groups with 2+ files
                    result_groups.append({
                        "base_name": base_name,
                        "directory": directory,
                        "extension": extension,
                        "files": files,
                        "detection_method": "explicit_marker"
                    })
            
            return result_groups
            
        finally:
            session.close()
    
    async def _find_similar_names(self, threshold: float) -> List[Dict]:
        """
        Find files with similar names (potential implicit versions).
        
        Criteria:
        - Same directory
        - Same extension
        - Levenshtein similarity >= threshold
        - Different content_hash (not duplicates)
        - Not already in a version chain
        
        Args:
            threshold: Minimum similarity ratio (0.0-1.0)
            
        Returns:
            List of potential version groups
        """
        session = self.get_sync_session()
        try:
            # Get all files not in version chains or marked as shortcuts
            result = session.execute(
                text("""
                    SELECT d.id, d.current_name, d.current_path, d.current_extension,
                           d.content_hash, d.source_modified_at, d.content_summary
                    FROM document_items d
                    LEFT JOIN duplicate_members dm ON d.id = dm.document_id AND dm.action = 'shortcut'
                    LEFT JOIN version_chain_members vcm ON d.id = vcm.document_id
                    WHERE d.content_hash IS NOT NULL
                      AND d.is_deleted = FALSE
                      AND dm.id IS NULL
                      AND vcm.id IS NULL
                    ORDER BY d.current_path, d.current_name
                """)
            )
            files = [dict(row._mapping) for row in result]
            
            # Group by directory + extension
            dir_ext_groups = defaultdict(list)
            for file in files:
                directory = str(Path(file['current_path']).parent)
                extension = file['current_extension']
                key = (directory, extension)
                dir_ext_groups[key].append(file)
            
            # Find similar names within each group
            result_groups = []
            processed_files = set()
            
            for (directory, extension), group_files in dir_ext_groups.items():
                if len(group_files) < 2:
                    continue
                
                # Compare each pair of files
                for i, file1 in enumerate(group_files):
                    if file1['id'] in processed_files:
                        continue
                    
                    similar_files = [file1]
                    name1 = Path(file1['current_name']).stem.lower()
                    
                    for file2 in group_files[i+1:]:
                        if file2['id'] in processed_files:
                            continue
                        
                        # Check if different content (not duplicates)
                        if file1['content_hash'] == file2['content_hash']:
                            continue
                        
                        # Check name similarity
                        name2 = Path(file2['current_name']).stem.lower()
                        similarity = levenshtein_ratio(name1, name2)
                        
                        if similarity >= threshold:
                            similar_files.append(file2)
                            processed_files.add(file2['id'])
                    
                    # Only create a group if we found similar files
                    if len(similar_files) >= 2:
                        processed_files.add(file1['id'])
                        
                        # Extract base name (common part)
                        base_name = self._extract_common_name(
                            [Path(f['current_name']).stem for f in similar_files]
                        )
                        
                        result_groups.append({
                            "base_name": base_name,
                            "directory": directory,
                            "extension": extension,
                            "files": similar_files,
                            "detection_method": "name_similarity"
                        })
            
            return result_groups
            
        finally:
            session.close()
    
    def _extract_common_name(self, names: List[str]) -> str:
        """
        Extract the common base name from a list of similar names.
        
        Args:
            names: List of file names (without extension)
            
        Returns:
            Common base name
        """
        if not names:
            return "document"
        
        if len(names) == 1:
            return names[0]
        
        # Find the longest common prefix
        common = self._find_common_prefix(names)
        
        # Clean up the common name
        common = self._clean_common_name(common)
        
        # If too short, extract base from first name
        if len(common) < 3:
            common = self._extract_base_from_name(names[0])
        
        return common or "document"
    
    def _find_common_prefix(self, names: List[str]) -> str:
        """Find the longest common prefix from a list of names."""
        common = names[0]
        for name in names[1:]:
            new_common = ""
            for c1, c2 in zip(common, name):
                if c1.lower() == c2.lower():
                    new_common += c1
                else:
                    break
            common = new_common
        return common
    
    def _clean_common_name(self, name: str) -> str:
        """Clean up common name by removing trailing punctuation."""
        return name.strip('_- ()')
    
    def _extract_base_from_name(self, name: str) -> str:
        """Extract base name by removing version markers and parenthetical suffixes."""
        # Remove parenthetical suffixes like " (1)", " (revised)"
        base = re.sub(r'[_\-\s]*\([^)]*\)$', '', name)
        # Remove common version markers
        base = re.sub(r'[_\-\s]*(v|version|rev|draft|final)\d*$', '', base, flags=re.IGNORECASE)
        return base.strip('_- ')
    
    async def _process_version_group(self, group: Dict):
        """
        Process a single version group.
        
        Args:
            group: Version group dictionary with files and metadata
        """
        try:
            files = group['files']
            
            # Skip single-file groups
            if len(files) < 2:
                return
            
            # For similar names, confirm with LLM
            if group['detection_method'] == 'name_similarity':
                confirmation = await self._confirm_versions_with_llm(files, group)
                if not confirmation or not confirmation.get('confirmed', False):
                    self.logger.info(
                        "version_group_rejected",
                        base_name=group['base_name'],
                        reason=confirmation.get('reasoning') if confirmation else 'LLM unavailable'
                    )
                    return
                
                llm_reasoning = confirmation.get('reasoning')
                current_idx = confirmation.get('current_index', len(files) - 1)
            else:
                # For explicit versions, use our sorting logic
                llm_reasoning = None
                current_idx = None
            
            # Sort files by version order (oldest to newest)
            sorted_files = self._sort_by_version(files)
            
            # Determine current version index
            if current_idx is None:
                current_idx = len(sorted_files) - 1  # Default to newest
            
            # Create version chain
            await self._create_version_chain(
                group=group,
                sorted_files=sorted_files,
                current_idx=current_idx,
                llm_reasoning=llm_reasoning
            )
            
        except Exception as e:
            self.logger.error(
                "process_version_group_error",
                base_name=group.get('base_name'),
                error=str(e)
            )
            self._errors.append({
                "base_name": group.get('base_name'),
                "error": str(e)
            })
    
    async def _confirm_versions_with_llm(
        self,
        files: List[Dict],
        group: Dict
    ) -> Optional[Dict]:
        """
        Ask Ollama to confirm version relationship for ambiguous cases.
        
        Args:
            files: List of file dictionaries
            group: Group metadata
            
        Returns:
            Dictionary with confirmation result, or None if LLM unavailable
        """
        try:
            # Build prompt with file information
            file_info = []
            for idx, file in enumerate(files):
                name = file['current_name']
                path = file['current_path']
                modified = file.get('source_modified_at', 'unknown')
                summary = file.get('content_summary', 'No summary available')
                
                # Truncate summary
                if summary and len(summary) > 200:
                    summary = summary[:200] + "..."
                
                file_info.append(
                    f"[{idx}] {name}\n"
                    f"    Path: {path}\n"
                    f"    Modified: {modified}\n"
                    f"    Summary: {summary}"
                )
            
            prompt = f"""Analyze these files to determine if they are versions of the same document:

{chr(10).join(file_info)}

Questions:
1. Are these different versions of the same document? (yes/no)
2. If yes, which file is the CURRENT (most recent) version? (provide index 0-{len(files)-1})
3. What is your reasoning?

Respond in this exact format:
CONFIRMED: yes/no
CURRENT_INDEX: <number>
REASONING: <your explanation>"""

            system_prompt = (
                "You are a document version analyzer. "
                "Determine if files are versions based on names, dates, and content summaries."
            )
            
            response = await self.ollama_service.generate(prompt, system_prompt)
            
            if not response:
                return None
            
            # Parse response
            confirmed = False
            current_index = len(files) - 1
            reasoning = response
            
            for line in response.split('\n'):
                if line.startswith('CONFIRMED:'):
                    confirmed = 'yes' in line.lower()
                elif line.startswith('CURRENT_INDEX:'):
                    try:
                        match = re.search(r'\d+', line)
                        if match:
                            idx = int(match.group())
                            if 0 <= idx < len(files):
                                current_index = idx
                    except:
                        pass
                elif line.startswith('REASONING:'):
                    reasoning = line.split(':', 1)[1].strip()
            
            return {
                "confirmed": confirmed,
                "current_index": current_index,
                "reasoning": reasoning
            }
            
        except Exception as e:
            self.logger.warning("llm_confirmation_error", error=str(e))
            return None
    
    def _sort_by_version(self, files: List[Dict]) -> List[Dict]:
        """
        Sort files in version order (oldest to newest).
        
        Priority:
        1. Version numbers (_v1 < _v2 < _v3)
        2. Dates (earlier < later)
        3. Status (draft < wip < review < approved < final)
        4. Modification date (fallback)
        
        Args:
            files: List of file dictionaries
            
        Returns:
            Sorted list (oldest to newest)
        """
        def sort_key(file):
            version_info = file.get('version_info', {})
            version_type = version_info.get('type', '')
            version_value = version_info.get('value', '')
            
            # Priority 1: Version numbers
            if version_type in ('version_number', 'revision_number', 'copy_number'):
                try:
                    return (1, int(version_value), 0, file.get('source_modified_at', datetime.min))
                except:
                    pass
            
            # Priority 2: Dates
            if version_type in ('date', 'date_compact'):
                try:
                    if version_type == 'date':
                        date_obj = datetime.strptime(version_value, '%Y-%m-%d')
                    else:  # date_compact
                        date_obj = datetime.strptime(version_value, '%Y%m%d')
                    return (2, 0, 0, date_obj)
                except:
                    pass
            
            # Priority 3: Status markers
            if version_type == 'status':
                status_rank = STATUS_PRIORITY.get(version_value.lower(), 99)
                return (3, status_rank, 0, file.get('source_modified_at', datetime.min))
            
            # Priority 4: Modification date fallback
            return (4, 0, 0, file.get('source_modified_at', datetime.min))
        
        return sorted(files, key=sort_key)
    
    async def _create_version_chain(
        self,
        group: Dict,
        sorted_files: List[Dict],
        current_idx: int,
        llm_reasoning: Optional[str]
    ):
        """
        Create version_chains and version_chain_members records.
        
        Args:
            group: Version group metadata
            sorted_files: Files sorted by version order (oldest to newest)
            current_idx: Index of the current version in sorted_files
            llm_reasoning: Optional LLM reasoning for the version relationship
        """
        session = self.get_sync_session()
        try:
            current_file = sorted_files[current_idx]
            base_name = group['base_name']
            base_path = group['directory']
            detection_method = group['detection_method']
            
            # Calculate confidence
            if detection_method == 'explicit_marker':
                confidence = 0.95
            else:
                confidence = 0.75  # Lower confidence for name similarity
            
            # Determine archive strategy
            archive_strategy = self.settings.version_archive_strategy.value
            
            # Calculate archive path based on strategy
            if archive_strategy == VersionArchiveStrategy.SUBFOLDER.value:
                archive_path = str(Path(base_path) / self.settings.version_folder_name / base_name)
            elif archive_strategy == VersionArchiveStrategy.INLINE.value:
                archive_path = base_path
            else:  # VersionArchiveStrategy.SEPARATE_ARCHIVE
                archive_path = f"/Archive/Versions/{base_name}"
            
            # Insert version chain
            chain_result = session.execute(
                text("""
                    INSERT INTO version_chains 
                    (chain_name, base_path, current_document_id, current_version_number,
                     detection_method, detection_confidence, llm_reasoning, 
                     version_order_confirmed, archive_strategy, archive_path)
                    VALUES 
                    (:chain_name, :base_path, :current_doc_id, :current_version,
                     :detection_method, :confidence, :llm_reasoning,
                     :confirmed, :archive_strategy, :archive_path)
                    RETURNING id
                """),
                {
                    "chain_name": base_name,
                    "base_path": base_path,
                    "current_doc_id": current_file['id'],
                    "current_version": current_idx + 1,
                    "detection_method": detection_method,
                    "confidence": confidence,
                    "llm_reasoning": llm_reasoning,
                    "confirmed": llm_reasoning is not None,
                    "archive_strategy": archive_strategy,
                    "archive_path": archive_path
                }
            )
            chain_id = chain_result.scalar()
            
            # Insert version chain members
            for idx, file in enumerate(sorted_files):
                is_current = (idx == current_idx)
                status = 'active' if is_current else 'superseded'
                version_number = idx + 1
                
                # Extract version label
                version_info = file.get('version_info', {})
                version_label = version_info.get('marker', f'v{version_number}')
                
                # Extract version date if available
                version_date = None
                if version_info.get('type') in ('date', 'date_compact'):
                    try:
                        date_str = version_info['value']
                        if version_info['type'] == 'date':
                            version_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        else:
                            version_date = datetime.strptime(date_str, '%Y%m%d').date()
                    except:
                        pass
                
                # Generate proposed names for archived versions
                if is_current:
                    # Current version keeps clean name
                    proposed_name = f"{base_name}.{group['extension']}"
                    proposed_path = str(Path(base_path) / proposed_name)
                else:
                    # Superseded versions get version suffix
                    mod_date = file.get('source_modified_at', datetime.now())
                    date_str = mod_date.strftime('%Y-%m-%d') if isinstance(mod_date, datetime) else ''
                    proposed_name = f"{base_name}_{version_label}_{date_str}.{group['extension']}"
                    proposed_path = str(Path(archive_path) / proposed_name)
                
                session.execute(
                    text("""
                        INSERT INTO version_chain_members
                        (chain_id, document_id, version_number, version_label, version_date,
                         is_current, status, proposed_version_name, proposed_version_path)
                        VALUES
                        (:chain_id, :doc_id, :version_num, :version_label, :version_date,
                         :is_current, :status, :proposed_name, :proposed_path)
                    """),
                    {
                        "chain_id": chain_id,
                        "doc_id": file['id'],
                        "version_num": version_number,
                        "version_label": version_label,
                        "version_date": version_date,
                        "is_current": is_current,
                        "status": status,
                        "proposed_name": proposed_name,
                        "proposed_path": proposed_path
                    }
                )
            
            session.commit()
            
            self._chains_created += 1
            self._versions_linked += len(sorted_files)
            
            self.logger.info(
                "version_chain_created",
                chain_id=chain_id,
                base_name=base_name,
                version_count=len(sorted_files),
                current_version=version_number,
                archive_strategy=archive_strategy
            )
            
            # Log to processing_log
            self.log_to_db(
                action="version_chain_created",
                document_id=current_file['id'],
                details={
                    "chain_id": chain_id,
                    "chain_name": base_name,
                    "version_count": len(sorted_files),
                    "detection_method": detection_method,
                    "archive_strategy": archive_strategy
                },
                success=True
            )
            
        except Exception as e:
            session.rollback()
            self.logger.error("create_version_chain_error", error=str(e), base_name=group.get('base_name'))
            raise
        finally:
            session.close()
