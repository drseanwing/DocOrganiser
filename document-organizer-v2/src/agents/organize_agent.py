"""
Organization Agent - Document Organization Planning with Claude.

Phase 4 of the processing pipeline (final phase):
1. Gather all processable files (excluding duplicates, superseded versions)
2. Build comprehensive inventory for Claude
3. Call Claude API for organization plan
4. Parse and validate Claude's response
5. Store organization plan in database
"""

import json
import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from collections import Counter
from typing import Optional, List, Dict, Any

from sqlalchemy import text

from src.config import ProcessingPhase, get_settings
from src.agents.base_agent import BaseAgent, AgentResult
from src.services.claude_service import ClaudeService


# System prompt for Claude
ORGANIZATION_SYSTEM_PROMPT = """You are an expert document management consultant specializing in file organization, naming conventions, and taxonomy design.

Your goal is to create a comprehensive, practical organization system that:
- Groups related files logically by purpose and project
- Uses consistent, meaningful naming conventions
- Creates a navigable directory hierarchy (max 4 levels deep)
- Assigns appropriate tags for filtering and searching
- Handles ALL file types appropriately

CRITICAL RULES:
1. EVERY file must be assigned - no files can be left out of file_assignments
2. When uncertain about categorization, preserve original location and name (set proposed_name and proposed_path to null)
3. Binary files (images, video, audio, executables) should be organized by filename patterns and metadata, not content
4. Unknown file extensions should be placed in /_Uncategorized with original names
5. Naming patterns must be practical and usable
6. Tag names should be lowercase with hyphens, max 3 levels deep in hierarchy
7. Directory paths must start with / and not exceed 4 levels (e.g., /Level1/Level2/Level3/Level4)

Respond with ONLY valid JSON - no markdown formatting, no explanations before or after the JSON."""


# Prompt template
ORGANIZATION_PROMPT_TEMPLATE = '''Analyze this file collection and create a comprehensive organization system.

## FILE INVENTORY ({file_count} files)

{file_inventory_json}

## CURRENT DIRECTORY STRUCTURE

{current_directories}

## FILE TYPE DISTRIBUTION

{type_distribution}

## YOUR TASK

Create an organization plan with:
1. Naming schemas for different document types
2. Hierarchical tag taxonomy for categorization
3. Optimized directory structure
4. Individual file assignments

## RESPONSE FORMAT

{{
  "naming_schemas": [
    {{
      "document_type": "string - type of document",
      "pattern": "string - naming pattern with placeholders",
      "example": "string - example filename",
      "description": "string - when to use this pattern",
      "placeholders": {{
        "placeholder_name": "description of placeholder"
      }}
    }}
  ],
  "tag_taxonomy": {{
    "root_tag": {{
      "description": "string - tag description",
      "color": "#hexcolor (optional)",
      "children": {{
        "child_tag": {{
          "description": "string",
          "children": {{ ... }}
        }}
      }}
    }}
  }},
  "directory_structure": [
    {{
      "path": "/path/to/directory",
      "purpose": "string - what goes here",
      "expected_types": ["extension1", "extension2"]
    }}
  ],
  "file_assignments": [
    {{
      "file_id": integer,
      "proposed_name": "new_filename.ext or null to keep original",
      "proposed_path": "/path/to/new/location or null to keep original",
      "proposed_tags": ["tag1", "tag2"],
      "reasoning": "string - why this organization"
    }}
  ]
}}

REMEMBER: Every file_id from the inventory MUST appear in file_assignments. When uncertain, use null for proposed_name and proposed_path.'''


class OrganizeAgent(BaseAgent):
    """
    Agent responsible for creating organization plans using Claude.
    
    Analyzes all processable files and generates:
    - Naming schemas per document type
    - Hierarchical tag taxonomy
    - Optimized directory structure
    - Individual file assignments
    """
    
    AGENT_NAME = "organize_agent"
    AGENT_PHASE = ProcessingPhase.ORGANIZING
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.claude_service = ClaudeService(self.settings)
        self._naming_schemas_created = 0
        self._tags_created = 0
        self._directories_planned = 0
        self._files_with_changes = 0
        self._files_unchanged = 0
        self._errors = []
    
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """
        Validate that files are indexed and processed.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        session = self.get_sync_session()
        try:
            # Check for processed documents
            result = session.execute(
                text("""
                    SELECT COUNT(*) FROM document_items 
                    WHERE status IN ('processed', 'organized') 
                    AND is_deleted = FALSE
                """)
            )
            processed_count = result.scalar()
            
            if processed_count == 0:
                return False, "No processed documents found. Run Index Agent first."
            
            # Check if Claude API is configured
            if not self.claude_service.is_configured():
                return False, "Claude API key not configured. Set ANTHROPIC_API_KEY environment variable."
            
            return True, ""
            
        finally:
            session.close()
    
    async def run(self, batch_id: Optional[str] = None) -> AgentResult:
        """
        Main entry point for organization planning.
        
        Args:
            batch_id: Optional batch ID for tracking
            
        Returns:
            AgentResult with organization statistics
        """
        start_time = datetime.utcnow()
        self.logger.info("organize_agent_starting")
        
        # Generate batch ID if not provided
        if not batch_id:
            batch_id = str(uuid.uuid4())
        
        # Validate prerequisites
        valid, error = await self.validate_prerequisites()
        if not valid:
            return AgentResult(success=False, error=error)
        
        self.update_job_phase(ProcessingPhase.ORGANIZING)
        
        try:
            # Step 1: Gather files for organization
            self.logger.info("gathering_files_for_organization")
            files = await self._gather_files_for_organization()
            
            if not files:
                duration = (datetime.utcnow() - start_time).total_seconds()
                return AgentResult(
                    success=True,
                    processed_count=0,
                    duration_seconds=duration,
                    metadata={
                        "naming_schemas_created": 0,
                        "tags_created": 0,
                        "directories_planned": 0,
                        "files_with_changes": 0,
                        "files_unchanged": 0,
                        "message": "No files to organize"
                    }
                )
            
            self.logger.info("files_gathered", count=len(files))
            self.start_processing(len(files))
            
            # Step 2: Get current directory structure
            current_dirs = await self._get_current_directories(files)
            
            # Step 3: Build Claude prompt
            prompt = self._build_organization_prompt(files, current_dirs)
            self.logger.info("prompt_built", length=len(prompt))
            
            # Step 4: Call Claude API
            self.logger.info("calling_claude_api")
            response = await self.claude_service.generate(
                prompt=prompt,
                system_prompt=ORGANIZATION_SYSTEM_PROMPT,
                max_retries=3
            )
            
            if not response:
                return AgentResult(
                    success=False,
                    error="Failed to get response from Claude API",
                    duration_seconds=(datetime.utcnow() - start_time).total_seconds()
                )
            
            self.logger.info("claude_response_received", length=len(response))
            
            # Step 5: Parse organization plan
            plan = await self._parse_organization_plan(response, files)
            
            if not plan:
                return AgentResult(
                    success=False,
                    error="Failed to parse Claude's organization plan",
                    duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                    metadata={"raw_response": response[:1000]}
                )
            
            self.logger.info("plan_parsed",
                           schemas=len(plan.get("naming_schemas", [])),
                           directories=len(plan.get("directory_structure", [])),
                           assignments=len(plan.get("file_assignments", [])))
            
            # Step 6: Store organization plan
            await self._store_naming_schemas(plan.get("naming_schemas", []), batch_id)
            await self._store_tag_taxonomy(plan.get("tag_taxonomy", {}), batch_id)
            await self._store_directory_structure(plan.get("directory_structure", []), batch_id)
            await self._store_file_assignments(plan.get("file_assignments", []), batch_id)
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            self.logger.info(
                "organize_agent_completed",
                naming_schemas=self._naming_schemas_created,
                tags=self._tags_created,
                directories=self._directories_planned,
                files_changed=self._files_with_changes,
                files_unchanged=self._files_unchanged,
                duration=duration
            )
            
            return AgentResult(
                success=True,
                processed_count=len(files),
                duration_seconds=duration,
                metadata={
                    "naming_schemas_created": self._naming_schemas_created,
                    "tags_created": self._tags_created,
                    "directories_planned": self._directories_planned,
                    "files_with_changes": self._files_with_changes,
                    "files_unchanged": self._files_unchanged,
                    "errors": self._errors
                }
            )
            
        except Exception as e:
            self.logger.error("organize_agent_error", error=str(e))
            duration = (datetime.utcnow() - start_time).total_seconds()
            return AgentResult(
                success=False,
                error=str(e),
                duration_seconds=duration
            )
    
    async def _gather_files_for_organization(self) -> List[Dict]:
        """
        Get all files that need organization planning.
        
        EXCLUDES:
        - Duplicates marked for 'shortcut' action
        - Superseded versions
        - Deleted files
        
        INCLUDES:
        - Primary duplicates (action = 'keep_primary')
        - Current versions (is_current = TRUE)
        - All other indexed files
        
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
                        d.current_extension,
                        d.file_size_bytes,
                        d.mime_type,
                        d.content_summary,
                        d.document_type,
                        d.key_topics,
                        d.source_modified_at,
                        vcm.is_current as is_version_current,
                        vc.chain_name as version_chain_name
                    FROM document_items d
                    LEFT JOIN duplicate_members dm ON d.id = dm.document_id AND dm.action = 'shortcut'
                    LEFT JOIN version_chain_members vcm ON d.id = vcm.document_id AND vcm.status = 'superseded'
                    LEFT JOIN version_chain_members vcm_current ON d.id = vcm_current.document_id
                    LEFT JOIN version_chains vc ON vcm_current.chain_id = vc.id
                    WHERE d.is_deleted = FALSE
                      AND d.status IN ('processed', 'discovered')
                      AND dm.id IS NULL  -- Not a shortcut duplicate
                      AND vcm.id IS NULL -- Not a superseded version
                    ORDER BY d.current_path, d.current_name
                """)
            )
            
            files = []
            for row in result:
                row_dict = dict(row._mapping)
                
                # Convert key_topics from list/array to proper format
                key_topics = row_dict.get('key_topics')
                if key_topics and not isinstance(key_topics, list):
                    key_topics = list(key_topics) if hasattr(key_topics, '__iter__') else []
                
                files.append({
                    "id": row_dict['id'],
                    "current_name": row_dict['current_name'],
                    "current_path": row_dict['current_path'],
                    "extension": row_dict['current_extension'],
                    "size_bytes": row_dict['file_size_bytes'],
                    "mime_type": row_dict['mime_type'],
                    "content_summary": row_dict['content_summary'],
                    "document_type": row_dict['document_type'],
                    "key_topics": key_topics or [],
                    "modified_at": row_dict['source_modified_at'].isoformat() if row_dict.get('source_modified_at') else None,
                    "is_version_current": row_dict.get('is_version_current'),
                    "version_chain_name": row_dict.get('version_chain_name')
                })
            
            return files
            
        finally:
            session.close()
    
    async def _get_current_directories(self, files: List[Dict]) -> List[str]:
        """
        Extract unique directory paths from file list.
        
        Args:
            files: List of file dictionaries
            
        Returns:
            Sorted list of unique directory paths
        """
        directories = set()
        
        for file in files:
            path = file.get('current_path', '')
            if path:
                # Extract directory from full path
                dir_path = str(Path(path).parent)
                directories.add(dir_path)
                
                # Also add parent directories
                parts = Path(dir_path).parts
                for i in range(1, len(parts) + 1):
                    parent = "/".join(parts[:i])
                    if parent:
                        directories.add("/" + parent.lstrip("/"))
        
        return sorted(directories)
    
    def _build_organization_prompt(
        self, 
        files: List[Dict], 
        current_structure: List[str]
    ) -> str:
        """
        Build comprehensive prompt for Claude.
        
        Args:
            files: List of file dictionaries
            current_structure: Current directory structure
            
        Returns:
            Formatted prompt string
        """
        # Build file inventory (limit detail for large collections)
        file_inventory = []
        for file in files:
            entry = {
                "id": file["id"],
                "name": file["current_name"],
                "path": file["current_path"],
                "extension": file["extension"],
                "size_bytes": file["size_bytes"],
            }
            
            # Include content summary if available (truncate if long)
            if file.get("content_summary"):
                summary = file["content_summary"]
                if len(summary) > 300:
                    summary = summary[:300] + "..."
                entry["summary"] = summary
            
            # Include document type if available
            if file.get("document_type"):
                entry["type"] = file["document_type"]
            
            # Include key topics if available
            if file.get("key_topics"):
                entry["topics"] = file["key_topics"][:5]  # Limit to 5 topics
            
            # Include version info if part of a chain
            if file.get("version_chain_name"):
                entry["version_chain"] = file["version_chain_name"]
            
            file_inventory.append(entry)
        
        # Build type distribution
        type_counts = Counter(f.get("extension", "unknown") for f in files)
        type_distribution = "\n".join(
            f"- {ext}: {count} files"
            for ext, count in type_counts.most_common()
        )
        
        # Format current directories
        current_dirs_str = "\n".join(current_structure[:50])  # Limit to 50 dirs
        if len(current_structure) > 50:
            current_dirs_str += f"\n... and {len(current_structure) - 50} more directories"
        
        # Build the prompt
        prompt = ORGANIZATION_PROMPT_TEMPLATE.format(
            file_count=len(files),
            file_inventory_json=json.dumps(file_inventory, indent=2, default=str),
            current_directories=current_dirs_str,
            type_distribution=type_distribution
        )
        
        return prompt
    
    async def _parse_organization_plan(
        self, 
        response: str,
        files: List[Dict]
    ) -> Optional[Dict]:
        """
        Parse Claude's JSON response.
        
        Args:
            response: Raw response text from Claude
            files: Original file list for validation
            
        Returns:
            Parsed and validated plan dict, or None on failure
        """
        # Try to extract JSON
        plan = self.claude_service._extract_json(response)
        
        if not plan:
            self.logger.error("failed_to_extract_json",
                            response_preview=response[:500])
            return None
        
        # Validate required fields
        required_fields = ["naming_schemas", "tag_taxonomy", 
                          "directory_structure", "file_assignments"]
        
        for field in required_fields:
            if field not in plan:
                self.logger.warning("missing_required_field", field=field)
                plan[field] = [] if field != "tag_taxonomy" else {}
        
        # Validate file assignments
        file_ids = {f["id"] for f in files}
        assigned_ids = {a["file_id"] for a in plan.get("file_assignments", [])}
        
        # Check for missing assignments
        missing_ids = file_ids - assigned_ids
        if missing_ids:
            self.logger.warning("files_missing_assignments",
                              count=len(missing_ids),
                              missing_ids=list(missing_ids)[:10])
            
            # Add default assignments for missing files
            for file in files:
                if file["id"] in missing_ids:
                    plan["file_assignments"].append({
                        "file_id": file["id"],
                        "proposed_name": None,
                        "proposed_path": None,
                        "proposed_tags": ["uncategorized"],
                        "reasoning": "Auto-assigned: file was not in Claude's response"
                    })
        
        # Validate directory structure paths
        valid_paths = {d["path"] for d in plan.get("directory_structure", [])}
        
        for assignment in plan.get("file_assignments", []):
            proposed_path = assignment.get("proposed_path")
            if proposed_path and proposed_path not in valid_paths:
                # Auto-create missing directory entry
                if proposed_path.startswith("/"):
                    plan["directory_structure"].append({
                        "path": proposed_path,
                        "purpose": "Auto-created for file assignment",
                        "expected_types": []
                    })
                    valid_paths.add(proposed_path)
        
        return plan
    
    async def _store_naming_schemas(
        self, 
        schemas: List[Dict], 
        batch_id: str
    ):
        """
        Insert/update naming_schema table.
        
        Args:
            schemas: List of naming schema dictionaries
            batch_id: Batch ID for tracking
        """
        session = self.get_sync_session()
        try:
            for schema in schemas:
                # Deactivate existing schema for this document type
                session.execute(
                    text("""
                        UPDATE naming_schema 
                        SET is_active = FALSE 
                        WHERE document_type = :doc_type AND is_active = TRUE
                    """),
                    {"doc_type": schema.get("document_type")}
                )
                
                # Insert new schema
                session.execute(
                    text("""
                        INSERT INTO naming_schema 
                        (document_type, naming_pattern, example, description, 
                         placeholders, is_active, created_by_batch)
                        VALUES 
                        (:doc_type, :pattern, :example, :description,
                         :placeholders::jsonb, TRUE, :batch_id)
                    """),
                    {
                        "doc_type": schema.get("document_type"),
                        "pattern": schema.get("pattern"),
                        "example": schema.get("example"),
                        "description": schema.get("description"),
                        "placeholders": json.dumps(schema.get("placeholders", {})),
                        "batch_id": batch_id
                    }
                )
                self._naming_schemas_created += 1
            
            session.commit()
            self.logger.info("naming_schemas_stored", count=self._naming_schemas_created)
            
        except Exception as e:
            session.rollback()
            self.logger.error("store_naming_schemas_error", error=str(e))
            self._errors.append({"action": "store_naming_schemas", "error": str(e)})
            raise
        finally:
            session.close()
    
    async def _store_tag_taxonomy(
        self, 
        taxonomy: Dict, 
        batch_id: str,
        parent_id: Optional[int] = None
    ):
        """
        Recursively insert tag_taxonomy (hierarchical).
        
        Args:
            taxonomy: Tag taxonomy dictionary (nested structure)
            batch_id: Batch ID for tracking
            parent_id: Parent tag ID for recursive insertion
        """
        session = self.get_sync_session()
        try:
            for tag_name, tag_data in taxonomy.items():
                # Skip if tag_data is not a dict
                if not isinstance(tag_data, dict):
                    continue
                
                # Check if tag already exists
                existing = session.execute(
                    text("SELECT id FROM tag_taxonomy WHERE tag_name = :name"),
                    {"name": tag_name}
                ).scalar()
                
                if existing:
                    # Update existing tag
                    session.execute(
                        text("""
                            UPDATE tag_taxonomy 
                            SET parent_tag_id = :parent_id,
                                description = :description,
                                color = :color,
                                is_active = TRUE
                            WHERE id = :id
                        """),
                        {
                            "id": existing,
                            "parent_id": parent_id,
                            "description": tag_data.get("description"),
                            "color": tag_data.get("color")
                        }
                    )
                    tag_id = existing
                else:
                    # Insert new tag
                    result = session.execute(
                        text("""
                            INSERT INTO tag_taxonomy 
                            (tag_name, parent_tag_id, description, color, is_active)
                            VALUES 
                            (:name, :parent_id, :description, :color, TRUE)
                            RETURNING id
                        """),
                        {
                            "name": tag_name,
                            "parent_id": parent_id,
                            "description": tag_data.get("description"),
                            "color": tag_data.get("color")
                        }
                    )
                    tag_id = result.scalar()
                    self._tags_created += 1
                
                session.commit()
                
                # Process children recursively
                children = tag_data.get("children", {})
                if children and isinstance(children, dict):
                    await self._store_tag_taxonomy(children, batch_id, tag_id)
            
        except Exception as e:
            session.rollback()
            self.logger.error("store_tag_taxonomy_error", error=str(e))
            self._errors.append({"action": "store_tag_taxonomy", "error": str(e)})
            raise
        finally:
            session.close()
    
    async def _store_directory_structure(
        self, 
        directories: List[Dict], 
        batch_id: str
    ):
        """
        Insert directory_structure table.
        
        Args:
            directories: List of directory dictionaries
            batch_id: Batch ID for tracking
        """
        session = self.get_sync_session()
        try:
            for directory in directories:
                path = directory.get("path")
                if not path:
                    continue
                
                # Calculate depth and extract folder name
                path_obj = Path(path)
                depth = len(path_obj.parts) - 1  # Subtract 1 for root
                folder_name = path_obj.name or "root"
                parent_path = str(path_obj.parent) if path_obj.parent != path_obj else None
                
                # Upsert directory
                session.execute(
                    text("""
                        INSERT INTO directory_structure 
                        (path, folder_name, parent_path, depth, purpose, 
                         expected_tags, expected_document_types, is_active, created_by_batch)
                        VALUES 
                        (:path, :folder_name, :parent_path, :depth, :purpose,
                         :expected_tags, :expected_types, TRUE, :batch_id)
                        ON CONFLICT (path) DO UPDATE SET
                            purpose = EXCLUDED.purpose,
                            expected_tags = EXCLUDED.expected_tags,
                            expected_document_types = EXCLUDED.expected_document_types,
                            is_active = TRUE,
                            created_by_batch = EXCLUDED.created_by_batch
                    """),
                    {
                        "path": path,
                        "folder_name": folder_name,
                        "parent_path": parent_path if parent_path != "/" else None,
                        "depth": depth,
                        "purpose": directory.get("purpose"),
                        "expected_tags": directory.get("expected_tags", []),
                        "expected_types": directory.get("expected_types", []),
                        "batch_id": batch_id
                    }
                )
                self._directories_planned += 1
            
            session.commit()
            self.logger.info("directory_structure_stored", count=self._directories_planned)
            
        except Exception as e:
            session.rollback()
            self.logger.error("store_directory_structure_error", error=str(e))
            self._errors.append({"action": "store_directory_structure", "error": str(e)})
            raise
        finally:
            session.close()
    
    async def _store_file_assignments(
        self, 
        assignments: List[Dict], 
        batch_id: str
    ):
        """
        Update document_items with proposed changes.
        
        Args:
            assignments: List of file assignment dictionaries
            batch_id: Batch ID for tracking
        """
        session = self.get_sync_session()
        try:
            for assignment in assignments:
                file_id = assignment.get("file_id")
                proposed_name = assignment.get("proposed_name")
                proposed_path = assignment.get("proposed_path")
                proposed_tags = assignment.get("proposed_tags", [])
                reasoning = assignment.get("reasoning")
                
                # Build full proposed path including filename
                full_proposed_path = None
                if proposed_path and proposed_name:
                    full_proposed_path = str(Path(proposed_path) / proposed_name)
                elif proposed_path:
                    full_proposed_path = proposed_path
                
                # Check if there are actual changes
                has_changes = proposed_name is not None or proposed_path is not None
                
                # Update document_items
                session.execute(
                    text("""
                        UPDATE document_items SET
                            proposed_name = :proposed_name,
                            proposed_path = :proposed_path,
                            proposed_tags = :proposed_tags,
                            organization_reasoning = :reasoning,
                            organization_batch_id = :batch_id,
                            status = 'organized',
                            organized_at = NOW()
                        WHERE id = :file_id
                    """),
                    {
                        "file_id": file_id,
                        "proposed_name": proposed_name,
                        "proposed_path": full_proposed_path,
                        "proposed_tags": proposed_tags,
                        "reasoning": reasoning,
                        "batch_id": batch_id
                    }
                )
                
                if has_changes:
                    self._files_with_changes += 1
                else:
                    self._files_unchanged += 1
                
                self.update_progress(f"Assigned file {file_id}")
            
            session.commit()
            self.logger.info("file_assignments_stored",
                           with_changes=self._files_with_changes,
                           unchanged=self._files_unchanged)
            
            # Log to processing_log
            self.log_to_db(
                action="organization_complete",
                details={
                    "files_with_changes": self._files_with_changes,
                    "files_unchanged": self._files_unchanged,
                    "naming_schemas": self._naming_schemas_created,
                    "tags": self._tags_created,
                    "directories": self._directories_planned
                },
                success=True
            )
            
        except Exception as e:
            session.rollback()
            self.logger.error("store_file_assignments_error", error=str(e))
            self._errors.append({"action": "store_file_assignments", "error": str(e)})
            raise
        finally:
            session.close()
