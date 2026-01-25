# PROMPT 3: File Execution Engine Implementation

## Context

You are implementing the **File Execution Engine** for a Document Organizer system. This is a Docker-containerized Python application that executes the planned file operations: creating directories, moving/renaming files, creating shortcuts for duplicates, and setting up version archive folders.

## System Architecture

The system uses:
- **Python 3.11** with async/await patterns
- **PostgreSQL** for metadata and operation tracking
- **Docker volumes** for file operations
- Local filesystem operations (no cloud APIs)

### Processing Pipeline Position
```
Index Agent → Dedup Agent → Version Agent → Organize Agent → EXECUTION ENGINE (you're building this)
```

The Execution Engine runs AFTER all planning is complete and (optionally) after human review/approval.

## Your Task

Implement `execution_engine.py` that:

1. **Creates directory structure** as planned
2. **Moves and renames files** according to assignments
3. **Creates shortcuts** for duplicate files
4. **Sets up version archives** with proper structure
5. **Generates manifest** tracking all changes for rollback
6. **Updates database** with final file states

## Volume Structure

```
/data/
├── source/          # Original extracted files (READ reference)
├── working/         # Reorganized structure (WRITE target)
├── output/          # Final ZIP output
└── reports/         # Manifests and reports
```

**CRITICAL**: Never modify `/data/source/`. Copy to `/data/working/` with new structure.

## Database Schema (Relevant Tables)

```sql
-- Document items with planned changes
-- Already populated by Organize Agent
SELECT 
    id,
    file_id,
    current_name,
    current_path,           -- Original location in /data/source/
    proposed_name,          -- New name (NULL = keep original)
    proposed_path,          -- New location (NULL = keep original)
    proposed_tags,
    has_name_change,        -- Generated column
    has_path_change,        -- Generated column
    status                  -- Should be 'organized'
FROM document_items;

-- Duplicates to convert to shortcuts
SELECT 
    dm.document_id,
    dm.action,              -- 'shortcut', 'keep_primary', 'keep_both'
    dm.is_primary,
    dg.primary_document_id,
    di.current_path AS primary_path
FROM duplicate_members dm
JOIN duplicate_groups dg ON dm.group_id = dg.id
JOIN document_items di ON dg.primary_document_id = di.id
WHERE dm.action = 'shortcut';

-- Version chains with archive plans
SELECT 
    vcm.document_id,
    vcm.version_number,
    vcm.is_current,
    vcm.status,             -- 'active', 'superseded'
    vcm.proposed_version_name,
    vcm.proposed_version_path,
    vc.archive_path,
    vc.archive_strategy
FROM version_chain_members vcm
JOIN version_chains vc ON vcm.chain_id = vc.id;

-- Directory structure to create
SELECT path, purpose FROM directory_structure WHERE is_active = TRUE;

-- Shortcut tracking (to populate)
CREATE TABLE shortcut_files (
    id SERIAL PRIMARY KEY,
    original_document_id INTEGER REFERENCES document_items(id),
    shortcut_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    shortcut_type VARCHAR(20) NOT NULL,  -- 'symlink', 'url', 'lnk'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    original_path TEXT NOT NULL,          -- For restoration
    original_hash VARCHAR(64)
);

-- Execution log
CREATE TABLE execution_log (
    id SERIAL PRIMARY KEY,
    job_id UUID,
    operation VARCHAR(50) NOT NULL,       -- 'create_dir', 'copy_file', 'rename', 'create_shortcut'
    source_path TEXT,
    target_path TEXT,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Execution Engine Class

```python
from pathlib import Path
from typing import Optional, List, Dict
import asyncio
import shutil
import json

from src.agents.base_agent import BaseAgent, AgentResult
from src.config import ProcessingPhase, get_settings

class ExecutionEngine(BaseAgent):
    AGENT_NAME = "execution_engine"
    AGENT_PHASE = ProcessingPhase.EXECUTING
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_root = Path(self.settings.data_source_path)
        self.working_root = Path(self.settings.data_working_path)
        self.manifest = []  # Track all operations
    
    async def validate_prerequisites(self) -> tuple[bool, str]:
        """Verify organization planning is complete."""
        pass
    
    async def run(self, dry_run: bool = False) -> AgentResult:
        """Execute all planned changes."""
        pass
```

## Required Methods

### 1. Pre-Execution Validation
```python
async def _validate_execution_plan(self) -> tuple[bool, list[str]]:
    """
    Validate the execution plan before starting.
    
    Checks:
    - All source files exist
    - No path conflicts (two files → same destination)
    - All proposed paths are valid
    - Sufficient disk space (estimate)
    - No circular references in shortcuts
    
    Returns: (is_valid, list_of_errors)
    """
```

### 2. Create Directory Structure
```python
async def _create_directories(self) -> int:
    """
    Create all directories from directory_structure table.
    
    Order: Create parents before children (sort by depth).
    
    In /data/working/:
    - Create each planned directory
    - Log each creation
    - Handle existing directories gracefully
    
    Returns: Number of directories created
    """
```

### 3. Copy/Rename Files
```python
async def _process_file_assignments(self) -> dict:
    """
    Process all file assignments from document_items.
    
    For each file:
    1. Determine source path: /data/source/{current_path}
    2. Determine target path: /data/working/{proposed_path}/{proposed_name}
    3. If no changes, copy to: /data/working/{current_path}/{current_name}
    4. Copy file (preserve metadata)
    5. Log operation
    6. Update document_items with final_name, final_path, status='applied'
    
    Returns: {"copied": N, "renamed": N, "moved": N, "unchanged": N, "errors": N}
    """
```

### 4. Create Shortcuts for Duplicates
```python
async def _create_shortcuts(self) -> int:
    """
    Create shortcuts for files marked as duplicates.
    
    For each duplicate with action='shortcut':
    1. Find the primary file's final location
    2. Determine shortcut location (where duplicate would have been)
    3. Create appropriate shortcut type:
       - Linux: symlink (preferred) or .desktop file
       - Cross-platform: .url file
    4. Record in shortcut_files table
    
    Returns: Number of shortcuts created
    """

def _create_symlink(self, target: Path, link_path: Path) -> bool:
    """Create a symbolic link."""
    pass

def _create_url_shortcut(self, target: Path, shortcut_path: Path) -> bool:
    """
    Create a .url file (Windows Internet Shortcut format).
    Works cross-platform as a pointer.
    
    Format:
    [InternetShortcut]
    URL=file:///path/to/target
    """
    pass

def _create_desktop_shortcut(self, target: Path, shortcut_path: Path) -> bool:
    """
    Create a .desktop file (Linux desktop entry).
    
    Format:
    [Desktop Entry]
    Type=Link
    Name=filename
    URL=file:///path/to/target
    """
    pass
```

### 5. Setup Version Archives
```python
async def _setup_version_archives(self) -> int:
    """
    Setup version archive structure for version chains.
    
    For each version chain:
    1. Create archive directory (based on archive_strategy)
    2. Copy superseded versions to archive with version names
    3. Ensure current version is in main location
    4. Create _version_history.json manifest
    
    Returns: Number of version archives created
    """

def _create_version_history_json(self, chain_id: int, archive_path: Path) -> dict:
    """
    Create version history manifest.
    
    Format:
    {
        "document_name": "Budget Report",
        "current_version": 3,
        "current_file": "../Budget_Report.xlsx",
        "archive_path": "/Documents/Finance/_versions/Budget_Report/",
        "versions": [
            {
                "version": 1,
                "file": "Budget_Report_v1_2024-01-10.xlsx",
                "date": "2024-01-10",
                "status": "superseded"
            },
            {
                "version": 2,
                "file": "Budget_Report_v2_2024-01-20.xlsx", 
                "date": "2024-01-20",
                "status": "superseded"
            },
            {
                "version": 3,
                "file": "../Budget_Report.xlsx",
                "date": "2024-02-01",
                "status": "current"
            }
        ],
        "generated_at": "2024-02-15T10:30:00Z"
    }
    """
    pass
```

### 6. Generate Organization Manifest
```python
async def _generate_manifest(self) -> Path:
    """
    Generate complete manifest of all changes.
    
    Saved to: /data/reports/{job_id}_manifest.json
    
    Format:
    {
        "job_id": "uuid",
        "executed_at": "ISO timestamp",
        "source_zip": "original.zip",
        "statistics": {
            "total_files": 500,
            "directories_created": 25,
            "files_copied": 480,
            "files_renamed": 200,
            "files_moved": 150,
            "shortcuts_created": 20,
            "version_archives": 15
        },
        "operations": [
            {
                "type": "copy",
                "source": "/data/source/old/path/file.docx",
                "target": "/data/working/new/path/renamed.docx",
                "document_id": 123
            },
            ...
        ],
        "shortcuts": [
            {
                "shortcut_path": "/data/working/path/shortcut.url",
                "target_path": "/data/working/primary/file.docx",
                "original_path": "/data/source/duplicate/file.docx"
            }
        ],
        "errors": [
            {"document_id": 456, "error": "Permission denied", "source": "..."}
        ]
    }
    """
    pass
```

### 7. Rollback Support
```python
async def rollback(self, manifest_path: str) -> bool:
    """
    Rollback changes using a manifest file.
    
    Steps:
    1. Load manifest
    2. Remove /data/working/ contents
    3. Restore original structure from /data/source/
    4. Clear execution_log for this job
    5. Reset document_items status to 'organized'
    
    Note: This is a simple rollback - just restore from source.
    The source directory is never modified.
    """
    pass
```

## Operation Order

Execute in this specific order to handle dependencies:

```
1. Validate execution plan
2. Clear /data/working/ directory
3. Create directory structure (parents first)
4. Copy all files (including unchanged ones to maintain structure)
5. Create shortcuts for duplicates
6. Setup version archives
7. Generate manifest
8. Update database with final states
```

## File Copy with Metadata

```python
async def _copy_file_with_metadata(self, source: Path, target: Path) -> bool:
    """
    Copy file preserving metadata.
    
    Preserve:
    - Modification time
    - Access time
    - Permissions (where possible)
    
    Use shutil.copy2() for metadata preservation.
    """
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return True
    except Exception as e:
        self.logger.error("copy_failed", source=str(source), error=str(e))
        return False
```

## Shortcut Types Comparison

| Type | Platform | Pros | Cons |
|------|----------|------|------|
| Symlink | Linux/Mac | Native, transparent | May not work on Windows shares |
| .url | All | Simple, readable | Not all apps follow |
| .lnk | Windows | Native Windows | Complex binary format |
| .desktop | Linux | Standard Linux | Linux-only |

**Recommendation**: Use symlinks as primary, fall back to .url files.

## Dry Run Mode

```python
async def run(self, dry_run: bool = False) -> AgentResult:
    """
    Execute changes.
    
    If dry_run=True:
    - Validate plan
    - Generate report of what WOULD happen
    - Don't create any files/directories
    - Return detailed preview
    """
```

## Error Handling

1. **File copy failures** - Log error, continue with other files, mark as failed
2. **Permission errors** - Log, skip file, include in error report
3. **Disk full** - Stop execution, report partial completion
4. **Path too long** - Truncate or report error
5. **Invalid characters** - Sanitize filenames

```python
def _sanitize_filename(self, filename: str) -> str:
    """
    Sanitize filename for cross-platform compatibility.
    
    Remove/replace:
    - < > : " / \ | ? *
    - Leading/trailing spaces
    - Trailing dots
    - Reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    """
    pass
```

## Expected Output

```python
AgentResult(
    success=True,
    processed_count=500,
    duration_seconds=45.3,
    metadata={
        "directories_created": 25,
        "files_copied": 480,
        "files_renamed": 200,
        "files_moved": 150,
        "shortcuts_created": 20,
        "version_archives": 15,
        "errors": [],
        "manifest_path": "/data/reports/abc123_manifest.json"
    }
)
```

## Progress Tracking

Report progress at each stage:
```python
self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=10)  # Directories
self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=50)  # Files
self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=80)  # Shortcuts
self.update_job_phase(ProcessingPhase.EXECUTING, progress_pct=95)  # Manifest
```

## Code Quality Requirements

- Async file operations where beneficial
- Comprehensive logging with structlog
- Transaction-safe database updates
- Type hints on all methods
- Docstrings explaining logic
- Graceful degradation on errors
- Progress tracking throughout

## Files to Create

1. `/src/execution/execution_engine.py` - Main execution engine
2. `/src/execution/shortcut_creator.py` - Shortcut creation utilities
3. `/src/execution/manifest_generator.py` - Manifest generation
4. `/src/execution/__init__.py` - Package exports

## Dependencies Available

```python
import os
import shutil
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List
from sqlalchemy import text
import structlog
```

---

Please implement the complete Execution Engine following this specification. Ensure robust error handling, comprehensive logging, and safe file operations that never modify the source directory.
