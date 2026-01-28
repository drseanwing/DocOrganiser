# Organization Agent Implementation

This document describes the implementation of the Organization Agent for the Document Organizer v2 system.

## Overview

The Organization Agent is the 4th phase in the processing pipeline, responsible for analyzing the complete file inventory and generating an intelligent organization plan using Claude AI (Anthropic).

**Pipeline Position:**
```
Index Agent → Dedup Agent → Version Agent → ORGANIZE AGENT (this) → Execution Engine
```

## Components

### 1. ClaudeService (`src/services/claude_service.py`)

Async wrapper for the Anthropic Claude API with the following features:

- **API Integration**: Connects to Claude API with proper authentication
- **Health Check**: Verifies API accessibility
- **Response Generation**: `generate()` method with retry logic and exponential backoff
- **JSON Extraction**: `generate_json()` method that handles:
  - Direct JSON parsing
  - Extraction from markdown code blocks (```json)
  - Flexible whitespace handling
- **Rate Limiting**: Respects Anthropic's rate limits with retry-after headers
- **Error Handling**: Comprehensive error logging with structlog

**Key Methods:**
```python
async def health_check() -> bool
async def generate(prompt: str, system_prompt: Optional[str] = None, 
                  max_retries: int = 3, temperature: float = 0.3) -> Optional[str]
async def generate_json(prompt: str, system_prompt: Optional[str] = None,
                       max_retries: int = 3) -> Optional[dict]
```

### 2. OrganizeAgent (`src/agents/organize_agent.py`)

Main agent that orchestrates the organization planning process.

**Key Features:**

#### File Gathering
- Queries database for processable files
- **Excludes:**
  - Duplicates marked for shortcut action
  - Superseded versions in version chains
  - Deleted files
- **Includes:**
  - Primary duplicates
  - Current versions
  - All other indexed files

#### Prompt Building
Creates comprehensive prompts for Claude containing:
- Complete file inventory with summaries (truncated for token efficiency)
- Current directory structure
- File type distribution
- Clear formatting instructions
- Critical rules (preserve originals when uncertain, handle all file types, etc.)

#### Response Validation
- Ensures every file has an assignment
- Validates all proposed paths exist in directory structure
- Validates all proposed tags exist in taxonomy
- Auto-creates missing directories if needed
- Logs errors if >10% of files are missing assignments

#### Data Storage
Stores the organization plan in four database tables:

1. **naming_schema**: Naming patterns per document type
2. **tag_taxonomy**: Hierarchical tag structure
3. **directory_structure**: Planned directory layout
4. **document_items**: Individual file assignments (proposed changes)

**Key Methods:**
```python
async def validate_prerequisites() -> tuple[bool, str]
async def run(force: bool = False) -> AgentResult
async def _gather_files_for_organization() -> List[Dict]
async def _get_current_directory_structure() -> List[str]
def _build_organization_prompt(files: List[Dict], current_structure: List[str]) -> str
async def _parse_organization_plan(response: dict, files: List[Dict]) -> Optional[Dict]
async def _store_organization_plan(plan: Dict)
```

## Database Schema

### naming_schema
```sql
CREATE TABLE naming_schema (
    id SERIAL PRIMARY KEY,
    document_type VARCHAR(100) NOT NULL,
    naming_pattern VARCHAR(500) NOT NULL,
    example VARCHAR(500),
    description TEXT,
    placeholders JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    schema_version INTEGER DEFAULT 1,
    created_by_batch UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### tag_taxonomy
```sql
CREATE TABLE tag_taxonomy (
    id SERIAL PRIMARY KEY,
    tag_name VARCHAR(100) NOT NULL UNIQUE,
    parent_tag_id INTEGER REFERENCES tag_taxonomy(id),
    description TEXT,
    color VARCHAR(7),
    usage_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### directory_structure
```sql
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
```

### document_items (updated fields)
```sql
-- Proposed changes from Organization Agent
proposed_name VARCHAR(500),
proposed_path TEXT,
proposed_tags TEXT[],
organization_reasoning TEXT,
organization_batch_id UUID,
organized_at TIMESTAMPTZ,
status = 'organized'
```

## Configuration

Required environment variables:

```bash
# Claude API Configuration
ANTHROPIC_API_KEY=sk-ant-...          # Required
CLAUDE_MODEL=claude-sonnet-4-20250514 # Default model
CLAUDE_MAX_TOKENS=16000                # Max response tokens

# Database Configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=7420
POSTGRES_DB=document_organizer
POSTGRES_USER=doc_organizer
POSTGRES_PASSWORD=changeme
```

## Usage

### Basic Usage

```python
from src.agents.organize_agent import OrganizeAgent
from src.config import get_settings

# Initialize agent
settings = get_settings()
agent = OrganizeAgent(settings=settings, job_id="some-uuid")

# Run organization
result = await agent.run()

if result.success:
    print(f"Organized {result.processed_count} files")
    print(f"Schemas created: {result.metadata['naming_schemas_created']}")
    print(f"Tags created: {result.metadata['tags_created']}")
    print(f"Directories planned: {result.metadata['directories_planned']}")
else:
    print(f"Error: {result.error}")
```

### With Force Regeneration

```python
# Regenerate plan even if files are already organized
result = await agent.run(force=True)
```

## Claude Prompt Structure

The agent sends Claude a structured prompt containing:

### 1. File Inventory
```json
[
  {
    "id": 123,
    "name": "budget_report.xlsx",
    "path": "/Documents/Finance/budget_report.xlsx",
    "extension": "xlsx",
    "size_bytes": 45000,
    "type": "report",
    "summary": "Q1 2024 budget breakdown...",
    "topics": ["budget", "finance", "Q1"]
  }
]
```

### 2. Current Directory Structure
```
/Documents
/Documents/Finance
/Documents/Projects
...
```

### 3. File Type Distribution
```
xlsx: 45 files
docx: 32 files
pdf: 28 files
...
```

### 4. Instructions
- Detailed rules for organization
- Output format specification
- Critical constraints (preserve originals when uncertain, etc.)

## Expected Claude Response

```json
{
  "naming_schemas": [
    {
      "document_type": "meeting_notes",
      "pattern": "{date}_{project}_Meeting-Notes",
      "example": "2024-01-15_ProjectAlpha_Meeting-Notes.docx",
      "description": "For meeting minutes and notes",
      "placeholders": {
        "date": "YYYY-MM-DD format",
        "project": "Project name"
      }
    }
  ],
  "tag_taxonomy": {
    "projects": {
      "description": "Project-related tags",
      "children": {
        "project-alpha": {"description": "Alpha project files"}
      }
    }
  },
  "directory_structure": [
    {
      "path": "/Documents",
      "purpose": "All document files",
      "expected_types": ["docx", "pdf", "xlsx"]
    }
  ],
  "file_assignments": [
    {
      "file_id": 123,
      "proposed_name": "2024-01-15_ProjectAlpha_Meeting-Notes.docx",
      "proposed_path": "/Documents/Projects/Alpha/Meetings",
      "proposed_tags": ["projects", "project-alpha", "meeting-notes"],
      "reasoning": "Meeting notes for Alpha project, dated naming applied"
    }
  ]
}
```

## File Type Handling

### Text-Based Files (Full Analysis)
- **Extensions**: docx, xlsx, pptx, pdf, txt, md, csv, html, json, xml
- **Strategy**: Use content summaries from Ollama for intelligent organization
- **Naming**: Based on content understanding

### Binary Files (Filename-Based)
- **Images**: jpg, png, gif, svg, etc.
- **Video**: mp4, avi, mov, etc.
- **Audio**: mp3, wav, flac, etc.
- **Strategy**: Organize by filename patterns and metadata
- **Naming**: Based on apparent purpose (screenshots, photos, graphics)

### Unknown Extensions
- **Strategy**: Place in `/_Uncategorized` folder
- **Naming**: Keep original names
- **Tags**: Mark as "uncategorized" for later review

## Error Handling

### API Failures
- Retry with exponential backoff (3 attempts)
- Cap backoff at 60 seconds
- Handle rate limiting with retry-after headers

### Response Validation
- Ensure all files have assignments
- Log warning if >10% files missing
- Auto-assign missing files to uncategorized

### Database Transactions
- Wrap all storage operations in transactions
- Rollback on any failure
- Log errors but continue with partial success

### Missing Resources
- Auto-create missing directories
- Log unknown tags but don't fail
- Preserve original file locations when uncertain

## Testing

Run the unit tests:

```bash
cd document-organizer-v2
python test_organize_agent.py
```

Tests cover:
- ClaudeService initialization
- JSON extraction from various formats
- Tag taxonomy flattening
- Tag counting
- Prompt building

## Logging

The agent uses structured logging (structlog) with the following events:

- `organize_agent_starting`: Agent initialization
- `gathering_files`: Before file query
- `files_gathered`: After successful file query
- `building_claude_prompt`: Before prompt construction
- `calling_claude_api`: Before API call
- `parsing_organization_plan`: After receiving response
- `missing_file_assignments`: If files not assigned by Claude
- `too_many_missing_assignments`: If >10% files missing
- `storing_organization_plan`: Before database storage
- `organize_agent_completed`: Successful completion
- `organize_agent_failed`: Fatal error

## Security

### CodeQL Analysis
All code has been analyzed with CodeQL and **0 security alerts** found.

### Best Practices
- API keys loaded from environment variables
- No secrets in code
- SQL injection prevention via parameterized queries
- Input validation on all external data
- Proper error handling to avoid information leakage

## Performance Considerations

### Token Optimization
- Content summaries truncated to 200 characters in prompts
- Directory structure limited to 50 entries in prompt
- Only essential file metadata included

### Batch Processing
- Processes all files in single Claude API call
- For very large inventories (>500 files), consider:
  - Batching into multiple calls
  - Summarizing file inventory
  - Grouping by file type first

### Rate Limiting
- Respects Anthropic rate limits
- Exponential backoff on errors
- Single API call per organization run minimizes rate issues

## Future Enhancements

Potential improvements:

1. **Batch Processing**: Split large inventories into multiple Claude calls
2. **Incremental Updates**: Only re-organize changed files
3. **User Preferences**: Allow user to specify organization preferences
4. **Machine Learning**: Learn from user corrections to improve future plans
5. **Preview Mode**: Generate plan without committing to database
6. **Alternative LLMs**: Support for other LLMs (GPT-4, Gemini, etc.)

## Support

For issues or questions:
- Check logs in `/data/logs/` (if configured)
- Review database state in relevant tables
- Verify Claude API key is valid and has sufficient quota
- Ensure prerequisite agents (Index, Dedup, Version) have completed

## License

Part of Document Organizer v2 system.
