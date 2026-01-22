"""
Organize Agent - AI-Powered Organization Planning.

Phase 4 of the processing pipeline:
1. Gather all processable files (excluding shortcuts and superseded versions)
2. Build comprehensive inventory for Claude
3. Call Claude API to generate organization plan
4. Parse and validate the organization plan
5. Store naming schemas, tag taxonomy, directory structure, and file assignments
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, List
from collections import Counter

from sqlalchemy import text

from src.config import ProcessingPhase, get_settings
from src.agents.base_agent import BaseAgent, AgentResult
from src.services.claude_service import ClaudeService


class OrganizeAgent(BaseAgent):
    """
    Agent responsible for generating an intelligent organization plan.
    
    Uses Claude to analyze the complete file inventory and create:
    - Naming schemas for different document types
    - Hierarchical tag taxonomy
    - Optimized directory structure
    - Individual file assignments
    """
    
    AGENT_NAME = "organize_agent"
    AGENT_PHASE = ProcessingPhase.ORGANIZING
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.claude_service = ClaudeService(self.settings)
        self._files_organized = 0
        self._errors = []
        self._batch_id = None
    
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """Check that files are indexed and processed."""
        session = self.get_sync_session()
        try:
            # Check if there are any indexed files
            result = session.execute(
                text("""
                    SELECT COUNT(*) as count
                    FROM document_items
                    WHERE status IN ('processed', 'organized')
                      AND is_deleted = FALSE
                """)
            )
            row = result.fetchone()
            if not row or row.count == 0:
                return False, "No processed files found. Run index_agent first."
            
            # Verify Claude API is accessible
            if not await self.claude_service.health_check():
                return False, f"Claude API not accessible. Check anthropic_api_key."
            
            return True, ""
            
        finally:
            session.close()
    
    async def run(self, force: bool = False) -> AgentResult:
        """
        Execute organization planning.
        
        Args:
            force: Regenerate plan even if files are already organized
            
        Returns:
            AgentResult with organization statistics
        """
        start_time = datetime.utcnow()
        self.logger.info("organize_agent_starting", force=force)
        
        # Validate prerequisites
        valid, error = await self.validate_prerequisites()
        if not valid:
            return AgentResult(success=False, error=error)
        
        self.update_job_phase(ProcessingPhase.ORGANIZING)
        self._batch_id = str(uuid.uuid4())
        
        try:
            # Step 1: Gather files for organization
            self.logger.info("gathering_files")
            files = await self._gather_files_for_organization()
            
            if not files:
                self.logger.info("no_files_to_organize")
                return AgentResult(
                    success=True,
                    processed_count=0,
                    duration_seconds=0.0,
                    metadata={"message": "No files to organize"}
                )
            
            self.start_processing(len(files))
            self.logger.info("files_gathered", count=len(files))
            
            # Step 2: Get current directory structure
            current_structure = await self._get_current_directory_structure()
            
            # Step 3: Build prompt for Claude
            self.logger.info("building_claude_prompt")
            prompt = self._build_organization_prompt(files, current_structure)
            
            # Step 4: Call Claude API
            self.logger.info("calling_claude_api", file_count=len(files))
            self.update_progress("Calling Claude API", 0)
            
            response = await self.claude_service.generate_json(
                prompt=prompt,
                system_prompt="You are an expert document management consultant. Respond with ONLY valid JSON, no markdown formatting or explanations.",
                max_retries=3
            )
            
            if not response:
                return AgentResult(
                    success=False,
                    error="Failed to get response from Claude API",
                    duration_seconds=self.get_elapsed_seconds()
                )
            
            # Step 5: Parse and validate organization plan
            self.logger.info("parsing_organization_plan")
            plan = await self._parse_organization_plan(response, files)
            
            if not plan:
                return AgentResult(
                    success=False,
                    error="Failed to parse Claude's organization plan",
                    duration_seconds=self.get_elapsed_seconds(),
                    metadata={"raw_response": str(response)[:1000]}
                )
            
            # Step 6: Store the organization plan
            self.logger.info("storing_organization_plan")
            await self._store_organization_plan(plan)
            
            # Calculate statistics
            files_with_changes = sum(
                1 for assignment in plan.get("file_assignments", [])
                if assignment.get("proposed_name") or assignment.get("proposed_path")
            )
            files_unchanged = len(files) - files_with_changes
            
            duration = self.get_elapsed_seconds()
            
            self.logger.info(
                "organize_agent_completed",
                files_organized=len(files),
                files_with_changes=files_with_changes,
                files_unchanged=files_unchanged,
                duration=duration
            )
            
            return AgentResult(
                success=True,
                processed_count=len(files),
                duration_seconds=duration,
                metadata={
                    "batch_id": self._batch_id,
                    "naming_schemas_created": len(plan.get("naming_schemas", [])),
                    "tags_created": self._count_tags(plan.get("tag_taxonomy", {})),
                    "directories_planned": len(plan.get("directory_structure", [])),
                    "files_with_changes": files_with_changes,
                    "files_unchanged": files_unchanged,
                    "errors": self._errors
                }
            )
            
        except Exception as e:
            self.logger.error("organize_agent_failed", error=str(e))
            return AgentResult(
                success=False,
                error=str(e),
                duration_seconds=self.get_elapsed_seconds(),
                metadata={"errors": self._errors}
            )
    
    async def _gather_files_for_organization(self) -> List[Dict]:
        """
        Get all files that need organization planning.
        
        EXCLUDE:
        - Duplicates marked for 'shortcut' action
        - Superseded versions (status = 'superseded')
        - Deleted files (is_deleted = TRUE)
        
        Returns:
            List of file dictionaries with metadata
        """
        session = self.get_sync_session()
        try:
            result = session.execute(
                text("""
                    SELECT 
                        d.id,
                        d.current_name,
                        d.current_path,
                        d.current_extension as extension,
                        d.file_size_bytes as size_bytes,
                        d.mime_type,
                        d.content_summary,
                        d.document_type,
                        d.key_topics,
                        d.source_modified_at as modified_at,
                        -- Check if it's in a version chain
                        COALESCE(vcm.is_current, TRUE) as is_version_current,
                        vc.chain_name as version_chain_name
                    FROM document_items d
                    -- Exclude duplicates marked for shortcut
                    LEFT JOIN duplicate_members dm ON d.id = dm.document_id
                    -- Check version chain membership
                    LEFT JOIN version_chain_members vcm ON d.id = vcm.document_id
                    LEFT JOIN version_chains vc ON vcm.chain_id = vc.id
                    WHERE d.is_deleted = FALSE
                      AND d.status IN ('processed', 'organized')
                      -- Exclude shortcuts
                      AND (dm.action IS NULL OR dm.action != 'shortcut')
                      -- Exclude superseded versions
                      AND (vcm.status IS NULL OR vcm.status != 'superseded')
                    ORDER BY d.current_path, d.current_name
                """)
            )
            
            files = []
            for row in result:
                files.append({
                    "id": row.id,
                    "current_name": row.current_name,
                    "current_path": row.current_path,
                    "extension": row.extension or "",
                    "size_bytes": row.size_bytes or 0,
                    "mime_type": row.mime_type or "",
                    "content_summary": row.content_summary or "",
                    "document_type": row.document_type or "unknown",
                    "key_topics": row.key_topics or [],
                    "modified_at": row.modified_at.isoformat() if row.modified_at else None,
                    "is_version_current": row.is_version_current,
                    "version_chain_name": row.version_chain_name
                })
            
            return files
            
        finally:
            session.close()
    
    async def _get_current_directory_structure(self) -> List[str]:
        """Get list of current directory paths."""
        session = self.get_sync_session()
        try:
            result = session.execute(
                text("""
                    SELECT DISTINCT 
                        regexp_replace(current_path, '/[^/]+$', '') as directory
                    FROM document_items
                    WHERE is_deleted = FALSE
                    ORDER BY directory
                """)
            )
            
            directories = [row.directory for row in result if row.directory]
            return directories
            
        finally:
            session.close()
    
    def _build_organization_prompt(self, files: List[Dict], current_structure: List[str]) -> str:
        """
        Build comprehensive prompt for Claude.
        
        The prompt includes:
        1. Complete file inventory with summaries
        2. Current directory structure
        3. File type distribution
        4. Clear instructions for output format
        """
        # Calculate file type distribution
        type_distribution = Counter(f["extension"] for f in files)
        
        # Build file inventory JSON (limit summary length for token efficiency)
        file_inventory = []
        for f in files:
            inventory_item = {
                "id": f["id"],
                "name": f["current_name"],
                "path": f["current_path"],
                "extension": f["extension"],
                "size_bytes": f["size_bytes"],
                "type": f["document_type"],
                "summary": (f["content_summary"][:200] + "...") if len(f.get("content_summary", "")) > 200 else f["content_summary"],
                "topics": f["key_topics"][:5] if f["key_topics"] else []
            }
            file_inventory.append(inventory_item)
        
        # Format type distribution
        type_dist_str = "\n".join(
            f"  {ext}: {count} files" 
            for ext, count in sorted(type_distribution.items(), key=lambda x: x[1], reverse=True)
        )
        
        # Format current structure
        structure_str = "\n".join(f"  {d}" for d in sorted(current_structure)[:50])
        if len(current_structure) > 50:
            structure_str += f"\n  ... and {len(current_structure) - 50} more directories"
        
        prompt = f'''You are an expert document management consultant. Analyze this file collection and create a comprehensive organization system.

## FILE INVENTORY ({len(files)} files)

{json.dumps(file_inventory, indent=2)}

## CURRENT DIRECTORY STRUCTURE

{structure_str if structure_str else "  (flat structure)"}

## FILE TYPE DISTRIBUTION

{type_dist_str}

## YOUR TASK

Create an organization plan that:
1. Groups related files logically
2. Uses consistent, meaningful naming conventions
3. Creates a navigable directory hierarchy (max 4 levels deep)
4. Assigns appropriate tags for filtering/searching
5. Handles ALL file types (documents, images, video, audio, archives, executables)

## CRITICAL RULES

1. **EVERY file must be assigned** - no files can be left out of file_assignments
2. **When uncertain, preserve original** - set proposed_name and proposed_path to null
3. **Binary files** (images, video, audio, exe) - organize by filename patterns, not content
4. **Unknown extensions** - place in /_Uncategorized with original names
5. **Naming patterns** - must be practical, avoid overly complex schemes
6. **Tags** - lowercase with hyphens, max 3 levels deep
7. **Directory paths** - use forward slashes, start with /, no trailing slash

## RESPONSE FORMAT

Respond with ONLY valid JSON (no markdown, no explanation):

{{
  "naming_schemas": [
    {{
      "document_type": "meeting_notes",
      "pattern": "{{date}}_{{project}}_Meeting-Notes",
      "example": "2024-01-15_ProjectAlpha_Meeting-Notes.docx",
      "description": "For meeting minutes and notes",
      "placeholders": {{
        "date": "YYYY-MM-DD format",
        "project": "Project name"
      }}
    }}
  ],
  "tag_taxonomy": {{
    "projects": {{
      "description": "Project-related tags",
      "children": {{
        "project-alpha": {{"description": "Alpha project files"}},
        "project-beta": {{"description": "Beta project files"}}
      }}
    }},
    "document-types": {{
      "description": "Type of document",
      "children": {{
        "reports": {{}},
        "meeting-notes": {{}},
        "policies": {{}}
      }}
    }},
    "media": {{
      "description": "Media files",
      "children": {{
        "images": {{"children": {{"photos": {{}}, "graphics": {{}}, "screenshots": {{}}}}}},
        "videos": {{}},
        "audio": {{}}
      }}
    }}
  }},
  "directory_structure": [
    {{
      "path": "/Documents",
      "purpose": "All document files",
      "expected_types": ["docx", "pdf", "xlsx"]
    }},
    {{
      "path": "/Documents/Projects",
      "purpose": "Active project documentation"
    }},
    {{
      "path": "/Media/Images",
      "purpose": "Image files"
    }},
    {{
      "path": "/_Uncategorized",
      "purpose": "Files that couldn't be confidently categorized"
    }}
  ],
  "file_assignments": [
    {{
      "file_id": 123,
      "proposed_name": "2024-01-15_ProjectAlpha_Meeting-Notes.docx",
      "proposed_path": "/Documents/Projects/Alpha/Meetings",
      "proposed_tags": ["projects", "project-alpha", "meeting-notes"],
      "reasoning": "Meeting notes for Alpha project"
    }},
    {{
      "file_id": 456,
      "proposed_name": null,
      "proposed_path": null,
      "proposed_tags": ["uncategorized"],
      "reasoning": "Unknown file type, keeping original location"
    }}
  ]
}}'''
        
        return prompt
    
    async def _parse_organization_plan(self, response: dict, files: List[Dict]) -> Optional[Dict]:
        """
        Parse and validate Claude's organization plan.
        
        Validation:
        - All required fields present
        - Every file has an assignment
        - All proposed_paths exist in directory_structure
        - All proposed_tags exist in tag_taxonomy
        """
        try:
            # Extract required sections
            naming_schemas = response.get("naming_schemas", [])
            tag_taxonomy = response.get("tag_taxonomy", {})
            directory_structure = response.get("directory_structure", [])
            file_assignments = response.get("file_assignments", [])
            
            # Validate: every file must have an assignment
            file_ids = {f["id"] for f in files}
            assigned_ids = {a["file_id"] for a in file_assignments}
            
            missing_ids = file_ids - assigned_ids
            if missing_ids:
                self.logger.warning("missing_file_assignments", count=len(missing_ids))
                # Add default assignments for missing files
                for file_id in missing_ids:
                    file_assignments.append({
                        "file_id": file_id,
                        "proposed_name": None,
                        "proposed_path": None,
                        "proposed_tags": ["uncategorized"],
                        "reasoning": "Not assigned by LLM, keeping original location"
                    })
            
            # Build set of valid directory paths
            valid_paths = {d["path"] for d in directory_structure}
            
            # Build set of valid tags (flatten taxonomy)
            valid_tags = self._flatten_tag_taxonomy(tag_taxonomy)
            
            # Validate and fix file assignments
            for assignment in file_assignments:
                # Validate proposed_path exists (if not null)
                if assignment.get("proposed_path") and assignment["proposed_path"] not in valid_paths:
                    # Try to find parent path
                    path = assignment["proposed_path"]
                    while path and path not in valid_paths:
                        parent = path.rsplit("/", 1)[0] if "/" in path else ""
                        if not parent or parent in valid_paths:
                            # Add missing directory
                            directory_structure.append({
                                "path": path,
                                "purpose": "Auto-created from file assignment",
                                "expected_types": []
                            })
                            valid_paths.add(path)
                            break
                        path = parent
                
                # Validate tags exist
                if assignment.get("proposed_tags"):
                    for tag in assignment["proposed_tags"]:
                        if tag not in valid_tags:
                            self.logger.warning("unknown_tag_in_assignment", tag=tag, file_id=assignment["file_id"])
            
            return {
                "naming_schemas": naming_schemas,
                "tag_taxonomy": tag_taxonomy,
                "directory_structure": directory_structure,
                "file_assignments": file_assignments
            }
            
        except Exception as e:
            self.logger.error("parse_organization_plan_failed", error=str(e))
            return None
    
    def _flatten_tag_taxonomy(self, taxonomy: dict, prefix: str = "") -> set:
        """Recursively flatten tag taxonomy to get all valid tag names."""
        tags = set()
        
        for tag_name, tag_data in taxonomy.items():
            full_tag = f"{prefix}{tag_name}" if prefix else tag_name
            tags.add(full_tag)
            
            # Recursively add children
            if isinstance(tag_data, dict) and "children" in tag_data:
                child_tags = self._flatten_tag_taxonomy(tag_data["children"], prefix=full_tag + "-")
                tags.update(child_tags)
        
        return tags
    
    def _count_tags(self, taxonomy: dict) -> int:
        """Count total tags in taxonomy."""
        count = len(taxonomy)
        for tag_data in taxonomy.values():
            if isinstance(tag_data, dict) and "children" in tag_data:
                count += self._count_tags(tag_data["children"])
        return count
    
    async def _store_organization_plan(self, plan: Dict):
        """Store the complete organization plan in database."""
        session = self.get_sync_session()
        try:
            # Store naming schemas
            await self._store_naming_schemas(plan["naming_schemas"], session)
            
            # Store tag taxonomy
            await self._store_tag_taxonomy(plan["tag_taxonomy"], session)
            
            # Store directory structure
            await self._store_directory_structure(plan["directory_structure"], session)
            
            # Store file assignments
            await self._store_file_assignments(plan["file_assignments"], session)
            
            session.commit()
            self.logger.info("organization_plan_stored")
            
        except Exception as e:
            session.rollback()
            self.logger.error("store_organization_plan_failed", error=str(e))
            raise
        finally:
            session.close()
    
    async def _store_naming_schemas(self, schemas: List[Dict], session):
        """Insert/update naming_schema table."""
        for schema in schemas:
            try:
                # Deactivate existing schemas for this document type
                session.execute(
                    text("""
                        UPDATE naming_schema
                        SET is_active = FALSE
                        WHERE document_type = :doc_type AND is_active = TRUE
                    """),
                    {"doc_type": schema["document_type"]}
                )
                
                # Insert new schema
                session.execute(
                    text("""
                        INSERT INTO naming_schema 
                        (document_type, naming_pattern, example, description, 
                         placeholders, created_by_batch)
                        VALUES 
                        (:doc_type, :pattern, :example, :description, 
                         :placeholders::jsonb, :batch_id)
                    """),
                    {
                        "doc_type": schema["document_type"],
                        "pattern": schema["pattern"],
                        "example": schema.get("example"),
                        "description": schema.get("description"),
                        "placeholders": json.dumps(schema.get("placeholders", {})),
                        "batch_id": self._batch_id
                    }
                )
                
            except Exception as e:
                self.logger.warning("store_naming_schema_failed", 
                                  document_type=schema["document_type"],
                                  error=str(e))
                self._errors.append(f"Failed to store naming schema: {str(e)}")
    
    async def _store_tag_taxonomy(
        self, 
        taxonomy: Dict, 
        session, 
        parent_id: Optional[int] = None,
        prefix: str = ""
    ):
        """
        Recursively insert tag_taxonomy (hierarchical).
        
        Args:
            taxonomy: Tag taxonomy dictionary
            session: Database session
            parent_id: Parent tag ID for hierarchy
            prefix: Prefix for tag names (for child tags)
        """
        for tag_name, tag_data in taxonomy.items():
            try:
                full_tag = f"{prefix}{tag_name}" if prefix else tag_name
                description = tag_data.get("description", "") if isinstance(tag_data, dict) else ""
                
                # Check if tag exists
                result = session.execute(
                    text("SELECT id FROM tag_taxonomy WHERE tag_name = :tag_name"),
                    {"tag_name": full_tag}
                )
                existing = result.fetchone()
                
                if existing:
                    tag_id = existing.id
                else:
                    # Insert new tag
                    result = session.execute(
                        text("""
                            INSERT INTO tag_taxonomy 
                            (tag_name, parent_tag_id, description)
                            VALUES (:tag_name, :parent_id, :description)
                            RETURNING id
                        """),
                        {
                            "tag_name": full_tag,
                            "parent_id": parent_id,
                            "description": description
                        }
                    )
                    tag_id = result.fetchone().id
                
                # Recursively process children
                if isinstance(tag_data, dict) and "children" in tag_data:
                    await self._store_tag_taxonomy(
                        tag_data["children"],
                        session,
                        parent_id=tag_id,
                        prefix=full_tag + "-"
                    )
                    
            except Exception as e:
                self.logger.warning("store_tag_failed", tag=tag_name, error=str(e))
                self._errors.append(f"Failed to store tag {tag_name}: {str(e)}")
    
    async def _store_directory_structure(self, directories: List[Dict], session):
        """Insert directory_structure table."""
        for directory in directories:
            try:
                path = directory["path"]
                folder_name = path.rsplit("/", 1)[-1] if "/" in path else path
                parent_path = path.rsplit("/", 1)[0] if "/" in path and path.count("/") > 1 else None
                depth = path.count("/")
                
                # Check if directory exists
                result = session.execute(
                    text("SELECT id FROM directory_structure WHERE path = :path"),
                    {"path": path}
                )
                
                if result.fetchone():
                    # Update existing
                    session.execute(
                        text("""
                            UPDATE directory_structure
                            SET purpose = :purpose,
                                expected_document_types = :types,
                                is_active = TRUE
                            WHERE path = :path
                        """),
                        {
                            "path": path,
                            "purpose": directory.get("purpose"),
                            "types": directory.get("expected_types", [])
                        }
                    )
                else:
                    # Insert new
                    session.execute(
                        text("""
                            INSERT INTO directory_structure
                            (path, folder_name, parent_path, depth, purpose, 
                             expected_document_types, created_by_batch)
                            VALUES 
                            (:path, :folder_name, :parent_path, :depth, :purpose,
                             :types, :batch_id)
                        """),
                        {
                            "path": path,
                            "folder_name": folder_name,
                            "parent_path": parent_path,
                            "depth": depth,
                            "purpose": directory.get("purpose"),
                            "types": directory.get("expected_types", []),
                            "batch_id": self._batch_id
                        }
                    )
                    
            except Exception as e:
                self.logger.warning("store_directory_failed", 
                                  path=directory["path"],
                                  error=str(e))
                self._errors.append(f"Failed to store directory: {str(e)}")
    
    async def _store_file_assignments(self, assignments: List[Dict], session):
        """
        Update document_items with proposed changes.
        
        For each assignment:
        - Set proposed_name (or NULL to keep original)
        - Set proposed_path (or NULL to keep original)
        - Set proposed_tags
        - Set organization_reasoning
        - Set status = 'organized'
        - Set organized_at = NOW()
        """
        for assignment in assignments:
            try:
                session.execute(
                    text("""
                        UPDATE document_items
                        SET proposed_name = :proposed_name,
                            proposed_path = :proposed_path,
                            proposed_tags = :proposed_tags,
                            organization_reasoning = :reasoning,
                            organization_batch_id = :batch_id,
                            organized_at = NOW(),
                            status = 'organized'
                        WHERE id = :file_id
                    """),
                    {
                        "file_id": assignment["file_id"],
                        "proposed_name": assignment.get("proposed_name"),
                        "proposed_path": assignment.get("proposed_path"),
                        "proposed_tags": assignment.get("proposed_tags", []),
                        "reasoning": assignment.get("reasoning", ""),
                        "batch_id": self._batch_id
                    }
                )
                
                self._files_organized += 1
                self.update_progress(f"Stored assignment for file {assignment['file_id']}", 1)
                
            except Exception as e:
                self.logger.warning("store_file_assignment_failed",
                                  file_id=assignment["file_id"],
                                  error=str(e))
                self._errors.append(f"Failed to store assignment for file {assignment['file_id']}: {str(e)}")
