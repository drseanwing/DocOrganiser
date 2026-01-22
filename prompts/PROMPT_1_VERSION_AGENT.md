# PROMPT 1: Version Control Agent Implementation

## Context

You are implementing the **Version Control Agent** for a Document Organizer system. This is a Docker-containerized Python application that processes files locally (extracted from a ZIP) to detect document versions, establish version chains, and plan archive structures.

## System Architecture

The system uses:
- **Python 3.11** with async/await patterns
- **PostgreSQL** for metadata storage
- **Ollama** (local LLM) for confirming version relationships
- **Docker Compose** for container orchestration

### Processing Pipeline Position
```
Index Agent → Dedup Agent → VERSION AGENT (you're building this) → Organize Agent
```

The Version Agent runs AFTER files have been indexed (with content hashes and summaries) and AFTER duplicates have been identified.

## Your Task

Implement `version_agent.py` that:

1. **Detects version patterns** in filenames:
   - Explicit markers: `_v1`, `_v2`, `_rev1`, `_version2`, `(1)`, `(2)`
   - Date patterns: `_2024-01-15`, `_20240115`
   - Status markers: `_draft`, `_final`, `_approved`, `_review`, `_wip`

2. **Finds similar-named files** that might be versions:
   - Same directory, same extension
   - High name similarity (Levenshtein ratio ≥ 0.7)
   - Different content hashes (not duplicates)

3. **Confirms version relationships** with Ollama:
   - For ambiguous cases, ask LLM to confirm files are versions
   - Determine version order (oldest → newest)
   - Identify which is CURRENT vs SUPERSEDED

4. **Establishes version chains** with archive strategy:
   - SUBFOLDER: `/doc/_versions/doc_v1.docx` (default)
   - INLINE: `doc_v1.docx` alongside `doc.docx`
   - SEPARATE_ARCHIVE: `/Archive/Versions/doc_v1.docx`

## Database Schema

```sql
-- Version chains (groups of related versions)
CREATE TABLE version_chains (
    id SERIAL PRIMARY KEY,
    chain_name VARCHAR(255) NOT NULL,          -- Base document name
    base_path TEXT,                             -- Common directory
    current_document_id INTEGER REFERENCES document_items(id),
    current_version_number INTEGER,
    detection_method VARCHAR(50),               -- 'explicit_marker', 'name_similarity', 'content_similarity'
    detection_confidence DECIMAL(3,2),          -- 0.00 to 1.00
    llm_reasoning TEXT,
    version_order_confirmed BOOLEAN DEFAULT FALSE,
    archive_strategy VARCHAR(50) DEFAULT 'subfolder',
    archive_path TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Individual versions within a chain
CREATE TABLE version_chain_members (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER REFERENCES version_chains(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES document_items(id),
    version_number INTEGER NOT NULL,
    version_label VARCHAR(50),                  -- 'v1', 'draft', 'final'
    version_date DATE,
    is_current BOOLEAN DEFAULT FALSE,
    status VARCHAR(50) DEFAULT 'active',        -- 'active', 'superseded', 'archived'
    proposed_version_name VARCHAR(500),
    proposed_version_path TEXT,
    CONSTRAINT valid_version_status CHECK (status IN ('active', 'superseded', 'archived'))
);

-- Document items table (already exists, relevant fields):
-- id, file_id, current_name, current_path, current_extension
-- content_hash, source_modified_at, content_summary
```

## Base Agent Class

Your agent must inherit from `BaseAgent`:

```python
from src.agents.base_agent import BaseAgent, AgentResult
from src.config import ProcessingPhase, VersionArchiveStrategy, get_settings
from src.services.ollama_service import OllamaService

class VersionAgent(BaseAgent):
    AGENT_NAME = "version_agent"
    AGENT_PHASE = ProcessingPhase.VERSIONING
    
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """Check indexing is complete."""
        pass
    
    async def run(self, similarity_threshold: float = 0.7) -> AgentResult:
        """Main entry point."""
        pass
```

## Required Methods

### 1. Pattern Detection
```python
VERSION_PATTERNS = [
    (r'_v(\d+)', 'version_number'),           # _v1, _v2
    (r'_rev(\d+)', 'revision_number'),        # _rev1, _rev2  
    (r'_version(\d+)', 'version_number'),     # _version1
    (r'\s*\((\d+)\)', 'copy_number'),         # (1), (2)
    (r'_(\d{4}-\d{2}-\d{2})', 'date'),        # _2024-01-15
    (r'_(\d{8})', 'date_compact'),            # _20240115
    (r'_(draft|final|approved|review|wip)', 'status'),
]

def _extract_version_info(self, filename: str) -> tuple[str, Optional[dict]]:
    """
    Extract version marker from filename.
    Returns: (base_name_without_marker, version_info_dict or None)
    
    Example:
        "Budget_v2.xlsx" → ("Budget", {"type": "version_number", "value": "2"})
        "Report_2024-01-15.docx" → ("Report", {"type": "date", "value": "2024-01-15"})
    """
```

### 2. Find Explicit Versions
```python
async def _find_explicit_versions(self) -> list[dict]:
    """
    Find files with explicit version markers, grouped by base name + directory.
    
    Returns list of groups:
    [
        {
            "base_name": "Budget",
            "directory": "/Documents/Finance",
            "extension": "xlsx",
            "files": [
                {"id": 1, "current_name": "Budget_v1.xlsx", "version_info": {...}},
                {"id": 2, "current_name": "Budget_v2.xlsx", "version_info": {...}},
            ],
            "detection_method": "explicit_marker"
        }
    ]
    """
```

### 3. Find Similar Names
```python
async def _find_similar_names(self, threshold: float) -> list[dict]:
    """
    Find files with similar names (potential implicit versions).
    
    Criteria:
    - Same directory
    - Same extension
    - Levenshtein similarity >= threshold
    - Different content_hash (not duplicates)
    - Not already in a version chain
    
    Use: from Levenshtein import ratio as levenshtein_ratio
    """
```

### 4. LLM Confirmation
```python
async def _confirm_versions_with_llm(self, files: list[dict], group: dict) -> Optional[dict]:
    """
    Ask Ollama to confirm version relationship for ambiguous cases.
    
    Prompt should include:
    - File names and paths
    - Modification dates
    - Content summaries (truncated)
    
    Expected response format:
    {
        "confirmed": true/false,
        "reasoning": "why these are/aren't versions",
        "current_index": 2,  # 0-based index of current version
        "version_order": [0, 1, 2]  # indices from oldest to newest
    }
    """
```

### 5. Sort by Version
```python
def _sort_by_version(self, files: list[dict]) -> list[dict]:
    """
    Sort files in version order (oldest to newest).
    
    Priority:
    1. Version numbers (_v1 < _v2 < _v3)
    2. Dates (earlier < later)
    3. Status (draft < wip < review < approved < final)
    4. Modification date (fallback)
    """
```

### 6. Create Version Chain
```python
async def _create_version_chain(
    self,
    group: dict,
    sorted_files: list[dict],
    current_idx: int,
    llm_reasoning: Optional[str]
):
    """
    Create version_chains and version_chain_members records.
    
    Naming for archived versions:
    - Current: "Budget.xlsx" (no version suffix, in original location)
    - Superseded: "Budget_v1_2024-01-10.xlsx" (in archive location)
    
    Archive paths based on strategy:
    - SUBFOLDER: "{base_path}/_versions/{base_name}/"
    - INLINE: "{base_path}/"
    - SEPARATE_ARCHIVE: "/Archive/Versions/{base_name}/"
    """
```

## Configuration (from src/config.py)

```python
class Settings:
    version_archive_strategy: VersionArchiveStrategy = VersionArchiveStrategy.SUBFOLDER
    version_folder_name: str = "_versions"
    version_patterns: list[str] = [...]  # Regex patterns
```

## Expected Output

`AgentResult` with:
```python
AgentResult(
    success=True,
    processed_count=15,  # Number of version chains created
    duration_seconds=45.2,
    metadata={
        "version_chains": 15,
        "versions_linked": 42,  # Total files linked to chains
        "explicit_groups": 10,
        "similar_groups": 5,
        "errors": []
    }
)
```

## Edge Cases to Handle

1. **Single file with version marker** - Don't create a chain for just one file
2. **Duplicates that are also versions** - Skip files already handled by Dedup Agent
3. **Conflicting version info** - e.g., `report_v2_draft.docx` has both version AND status
4. **Cross-directory versions** - Generally don't link, but LLM might confirm
5. **No clear current version** - Default to most recently modified
6. **Circular references** - A file can only be in one version chain

## Testing Scenarios

1. **Explicit versions**: `budget_v1.xlsx`, `budget_v2.xlsx`, `budget_v3.xlsx`
2. **Date versions**: `report_2024-01-01.pdf`, `report_2024-02-01.pdf`
3. **Status versions**: `proposal_draft.docx`, `proposal_final.docx`
4. **Similar names**: `Meeting Notes.docx`, `Meeting Notes (revised).docx`
5. **Mixed patterns**: `plan_v1_draft.pptx`, `plan_v2_final.pptx`

## Code Quality Requirements

- Async/await throughout
- Comprehensive logging with structlog
- Database transactions with proper rollback
- Type hints on all methods
- Docstrings explaining logic
- Error handling with graceful degradation
- Progress tracking via `self.update_progress()`

## Files to Create

1. `/src/agents/version_agent.py` - Main agent implementation
2. Update `/src/agents/__init__.py` to export VersionAgent

## Dependencies Available

```python
import re
import asyncio
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Optional, List
from Levenshtein import ratio as levenshtein_ratio
from sqlalchemy import text
```

---

Please implement the complete Version Agent following this specification. Include comprehensive error handling, logging, and ensure all database operations use proper transaction management.
