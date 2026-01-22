# PROMPT 2: Organization Agent Implementation

## Context

You are implementing the **Organization Agent** for a Document Organizer system. This is a Docker-containerized Python application that uses Claude (Anthropic API) to analyze a complete file inventory and generate an intelligent organization plan including naming schemas, tag taxonomies, and directory structures.

## System Architecture

The system uses:
- **Python 3.11** with async/await patterns
- **PostgreSQL** for metadata storage
- **Claude API** (Anthropic) for organization planning
- **Docker Compose** for container orchestration

### Processing Pipeline Position
```
Index Agent → Dedup Agent → Version Agent → ORGANIZE AGENT (you're building this)
```

The Organization Agent runs LAST, after:
- Files are indexed with content summaries
- Duplicates are identified (some marked for shortcuts)
- Version chains are established (superseded versions identified)

## Your Task

Implement `organize_agent.py` that:

1. **Gathers all processable files** - excluding duplicates marked for shortcuts and superseded versions
2. **Builds comprehensive inventory** for Claude with summaries, types, current structure
3. **Calls Claude API** with a well-structured prompt
4. **Parses Claude's organization plan** containing:
   - Naming schemas per document type
   - Hierarchical tag taxonomy
   - Optimized directory structure
   - Individual file assignments
5. **Stores the plan** in database tables for execution phase

## Supported File Types

The system handles ALL file types, not just documents:

| Category | Extensions | Organization Notes |
|----------|------------|-------------------|
| Documents | docx, doc, pdf, txt, md, rtf | Full content analysis available |
| Spreadsheets | xlsx, xls, csv | Full content analysis available |
| Presentations | pptx, ppt | Full content analysis available |
| Images | jpg, jpeg, png, gif, bmp, tiff, svg, webp | Organize by metadata/filename only |
| Video | mp4, avi, mov, mkv, wmv, flv, webm | Organize by metadata/filename only |
| Audio | mp3, wav, flac, aac, ogg, wma | Organize by metadata/filename only |
| Archives | zip, rar, 7z, tar, gz | Organize by filename only |
| Code | py, js, html, css, json, xml, yaml | Content available |
| Executables | exe, msi, dmg, app | Organize by filename only |
| Other | Any unknown extension | Best-effort by filename |

**Critical Rule**: If the LLM cannot confidently categorize/rename a file, it should remain in its original location with original name. Never lose files by failing to assign them.

## Database Schema

```sql
-- Naming schemas per document type
CREATE TABLE naming_schema (
    id SERIAL PRIMARY KEY,
    document_type VARCHAR(100) NOT NULL,
    naming_pattern VARCHAR(500) NOT NULL,      -- e.g., "{date}_{project}_{type}"
    example VARCHAR(500),
    description TEXT,
    placeholders JSONB,                         -- Available placeholders
    is_active BOOLEAN DEFAULT TRUE,
    schema_version INTEGER DEFAULT 1,
    created_by_batch UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(document_type, is_active) WHERE is_active = TRUE
);

-- Hierarchical tag taxonomy
CREATE TABLE tag_taxonomy (
    id SERIAL PRIMARY KEY,
    tag_name VARCHAR(100) NOT NULL UNIQUE,
    parent_tag_id INTEGER REFERENCES tag_taxonomy(id),
    description TEXT,
    color VARCHAR(7),                           -- Hex color for UI
    usage_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Directory structure plan
CREATE TABLE directory_structure (
    id SERIAL PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    folder_name VARCHAR(255) NOT NULL,
    parent_path TEXT,
    depth INTEGER NOT NULL,
    purpose TEXT,
    expected_tags TEXT[],
    expected_document_types TEXT[],
    file_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_by_batch UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Document items (already exists, fields to UPDATE):
-- proposed_name VARCHAR(500)
-- proposed_path TEXT  
-- proposed_tags TEXT[]
-- organization_reasoning TEXT
-- organization_batch_id UUID
-- organized_at TIMESTAMPTZ
-- status = 'organized'
```

## Base Agent Class

```python
from src.agents.base_agent import BaseAgent, AgentResult
from src.config import ProcessingPhase, get_settings
from src.services.claude_service import ClaudeService

class OrganizeAgent(BaseAgent):
    AGENT_NAME = "organize_agent"
    AGENT_PHASE = ProcessingPhase.ORGANIZING
    
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """Check that files are indexed and processed."""
        pass
    
    async def run(self) -> AgentResult:
        """Main entry point."""
        pass
```

## Claude Service (to create)

```python
# src/services/claude_service.py
import httpx
from typing import Optional
from src.config import Settings

class ClaudeService:
    def __init__(self, settings: Settings):
        self.api_key = settings.anthropic_api_key
        self.model = settings.claude_model  # claude-sonnet-4-20250514
        self.max_tokens = settings.claude_max_tokens  # 16000
        self.base_url = "https://api.anthropic.com/v1/messages"
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """Call Claude API and return response text."""
        pass
```

## Required Methods

### 1. Gather Processable Files
```python
async def _gather_files_for_organization(self) -> list[dict]:
    """
    Get all files that need organization planning.
    
    EXCLUDE:
    - Duplicates marked for 'shortcut' action (duplicate_members.action = 'shortcut')
    - Superseded versions (version_chain_members.status = 'superseded')
    - Deleted files (is_deleted = TRUE)
    
    INCLUDE:
    - Primary duplicates (action = 'keep_primary')
    - Current versions (is_current = TRUE)
    - All other indexed files
    
    Return format:
    [
        {
            "id": 123,
            "current_name": "budget_report.xlsx",
            "current_path": "/Documents/Finance/budget_report.xlsx",
            "extension": "xlsx",
            "size_bytes": 45000,
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content_summary": "Q1 2024 budget breakdown by department...",
            "document_type": "report",  # From Ollama analysis
            "key_topics": ["budget", "finance", "Q1"],
            "modified_at": "2024-01-15T10:30:00Z",
            "is_version_current": True,  # If in a version chain
            "version_chain_name": "Budget Report"  # If applicable
        }
    ]
    """
```

### 2. Build Claude Prompt
```python
def _build_organization_prompt(self, files: list[dict], current_structure: list[str]) -> str:
    """
    Build comprehensive prompt for Claude.
    
    The prompt should include:
    1. Complete file inventory with summaries
    2. Current directory structure
    3. File type distribution
    4. Clear instructions for output format
    
    CRITICAL INSTRUCTIONS FOR CLAUDE:
    - Every file MUST be assigned (no files left unassigned)
    - Files without clear categorization stay in original location
    - Binary files (images, video, audio, exe) use filename-based organization
    - Naming schemas must be practical and consistent
    - Directory depth should not exceed 4 levels
    """
```

### 3. Expected Claude Response Format
```python
EXPECTED_RESPONSE = {
    "naming_schemas": [
        {
            "document_type": "meeting_notes",
            "pattern": "{date}_{project}_Meeting-Notes",
            "example": "2024-01-15_ProjectAlpha_Meeting-Notes.docx",
            "description": "For meeting minutes and notes",
            "placeholders": {
                "date": "YYYY-MM-DD format",
                "project": "Project name, lowercase with hyphens"
            }
        },
        {
            "document_type": "image",
            "pattern": "{category}_{descriptor}_{date}",
            "example": "marketing_hero-banner_2024-01.png",
            "description": "For image files",
            "placeholders": {
                "category": "Usage category",
                "descriptor": "Brief description",
                "date": "YYYY-MM format"
            }
        }
    ],
    "tag_taxonomy": {
        "projects": {
            "description": "Project-related tags",
            "children": {
                "project-alpha": {"description": "Alpha project files"},
                "project-beta": {"description": "Beta project files"}
            }
        },
        "document-types": {
            "description": "Type of document",
            "children": {
                "reports": {},
                "meeting-notes": {},
                "policies": {}
            }
        },
        "media": {
            "description": "Media files",
            "children": {
                "images": {"children": {"photos": {}, "graphics": {}, "screenshots": {}}},
                "videos": {},
                "audio": {}
            }
        }
    },
    "directory_structure": [
        {
            "path": "/Documents",
            "purpose": "All document files",
            "expected_types": ["docx", "pdf", "xlsx"]
        },
        {
            "path": "/Documents/Projects",
            "purpose": "Active project documentation"
        },
        {
            "path": "/Media/Images",
            "purpose": "Image files organized by use"
        },
        {
            "path": "/Media/Videos",
            "purpose": "Video files"
        },
        {
            "path": "/Archives",
            "purpose": "Old/completed project files"
        },
        {
            "path": "/_Uncategorized",
            "purpose": "Files that couldn't be confidently categorized"
        }
    ],
    "file_assignments": [
        {
            "file_id": 123,
            "proposed_name": "2024-01-15_ProjectAlpha_Meeting-Notes.docx",
            "proposed_path": "/Documents/Projects/Alpha/Meetings",
            "proposed_tags": ["projects", "project-alpha", "meeting-notes"],
            "reasoning": "Meeting notes for Alpha project, dated naming applied"
        },
        {
            "file_id": 456,
            "proposed_name": null,  # Keep original name
            "proposed_path": null,  # Keep original path
            "proposed_tags": ["uncategorized"],
            "reasoning": "Unknown file type, cannot confidently categorize"
        }
    ]
}
```

### 4. Parse Claude Response
```python
async def _parse_organization_plan(self, response: str) -> Optional[dict]:
    """
    Parse Claude's JSON response.
    
    Handle:
    - JSON extraction from markdown code blocks
    - Validation of required fields
    - Default values for missing optional fields
    
    Validation rules:
    - Every file in input must have an assignment in file_assignments
    - All proposed_paths must exist in directory_structure
    - All proposed_tags must exist in tag_taxonomy
    - Naming patterns must have valid placeholders
    """
```

### 5. Store Organization Plan
```python
async def _store_naming_schemas(self, schemas: list[dict], batch_id: str):
    """Insert/update naming_schema table."""
    pass

async def _store_tag_taxonomy(self, taxonomy: dict, batch_id: str, parent_id: int = None):
    """Recursively insert tag_taxonomy (hierarchical)."""
    pass

async def _store_directory_structure(self, directories: list[dict], batch_id: str):
    """Insert directory_structure table."""
    pass

async def _store_file_assignments(self, assignments: list[dict], batch_id: str):
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
    pass
```

## Handling Different File Types

### Text-Based (Full Analysis)
- docx, xlsx, pptx, pdf, txt, md, csv, html, json, xml
- Have content_summary from Ollama
- Can be named based on content understanding

### Binary (Filename-Based)
- Images: Organize by apparent purpose (screenshots, photos, graphics)
- Video: Organize by apparent type (tutorials, recordings, clips)
- Audio: Organize by apparent type (music, recordings, podcasts)
- Archives: Keep together, possibly by apparent project
- Executables: Separate folder, organized by apparent purpose

### Unknown Extensions
- Create `/_Uncategorized` folder
- Keep original names
- Tag as "uncategorized" for later review

## Claude Prompt Template

```python
ORGANIZATION_PROMPT = '''You are an expert document management consultant. Analyze this file collection and create a comprehensive organization system.

## FILE INVENTORY ({file_count} files)

{file_inventory_json}

## CURRENT DIRECTORY STRUCTURE

{current_directories}

## FILE TYPE DISTRIBUTION

{type_distribution}

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

## RESPONSE FORMAT

Respond with ONLY valid JSON (no markdown, no explanation):

{{
  "naming_schemas": [...],
  "tag_taxonomy": {{...}},
  "directory_structure": [...],
  "file_assignments": [...]
}}

See the expected format specification for exact schema.'''
```

## Expected Output

`AgentResult` with:
```python
AgentResult(
    success=True,
    processed_count=150,  # Files with assignments
    duration_seconds=30.5,
    metadata={
        "naming_schemas_created": 8,
        "tags_created": 25,
        "directories_planned": 15,
        "files_with_changes": 120,  # Files that will be renamed/moved
        "files_unchanged": 30,      # Files staying in place
        "errors": []
    }
)
```

## Error Handling

1. **Claude API failure** - Retry with exponential backoff (3 attempts)
2. **Invalid JSON response** - Try to extract JSON, log raw response
3. **Missing file assignments** - Log warning, mark unassigned files as unchanged
4. **Invalid paths/tags** - Auto-create missing directories/tags
5. **Rate limiting** - Respect Anthropic rate limits

## Edge Cases

1. **Empty inventory** - Return early with success, no changes
2. **Very large inventory** (>500 files) - Consider batching or summarizing
3. **All binary files** - Still create meaningful structure
4. **Deeply nested current structure** - Flatten appropriately
5. **Conflicting naming suggestions** - Claude should ensure uniqueness

## Code Quality Requirements

- Async/await throughout
- Comprehensive logging with structlog
- Database transactions with proper rollback
- Type hints on all methods
- Docstrings explaining logic
- Retry logic for API calls
- Progress tracking via `self.update_progress()`

## Files to Create

1. `/src/agents/organize_agent.py` - Main agent implementation
2. `/src/services/claude_service.py` - Claude API wrapper
3. Update `/src/agents/__init__.py` to export OrganizeAgent
4. Update `/src/services/__init__.py` to export ClaudeService

## Dependencies Available

```python
import json
import asyncio
import httpx
from datetime import datetime
from typing import Optional, Dict, List
from collections import Counter
from sqlalchemy import text
```

## Configuration (from src/config.py)

```python
class Settings:
    anthropic_api_key: Optional[str]
    claude_model: str = "claude-sonnet-4-20250514"
    claude_max_tokens: int = 16000
```

---

Please implement the complete Organization Agent and Claude Service following this specification. Ensure robust error handling for API calls and comprehensive validation of Claude's responses.
