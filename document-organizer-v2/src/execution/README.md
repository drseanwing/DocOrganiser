# Execution Engine

The Execution Engine is responsible for executing all planned file operations after the indexing, deduplication, versioning, and organization phases are complete.

## Overview

The Execution Engine takes planned changes from the database and physically executes them:
- Creates directory structures
- Copies/moves/renames files
- Creates shortcuts for duplicates
- Sets up version archives
- Generates comprehensive manifests
- Supports rollback functionality

## Architecture

### Components

1. **ExecutionEngine** (`execution_engine.py`)
   - Main orchestrator inheriting from `BaseAgent`
   - Coordinates all execution phases
   - Manages database transactions
   - Tracks progress and errors

2. **ShortcutCreator** (`shortcut_creator.py`)
   - Creates different types of file shortcuts
   - Supports symlinks, .url files, and .desktop files
   - Auto-fallback strategy for cross-platform compatibility

3. **ManifestGenerator** (`manifest_generator.py`)
   - Tracks all operations performed
   - Generates JSON manifests for audit trail
   - Enables rollback functionality

## Usage

### Basic Execution

```python
from src.execution import ExecutionEngine

engine = ExecutionEngine(job_id="your-job-uuid")

# Validate prerequisites
is_valid, error = await engine.validate_prerequisites()
if not is_valid:
    print(f"Prerequisites not met: {error}")
    return

# Execute changes
result = await engine.run(dry_run=False)

if result.success:
    print(f"Execution complete: {result.processed_count} files processed")
    print(f"Manifest: {result.metadata['manifest_path']}")
else:
    print(f"Execution failed: {result.error}")
```

### Dry-Run Mode

Preview changes without executing:

```python
result = await engine.run(dry_run=True)
preview = result.metadata["preview"]
print(f"Would create {preview['directories_to_create']} directories")
print(f"Would process {preview['files_to_process']} files")
print(f"Would create {preview['shortcuts_to_create']} shortcuts")
```

### Rollback

Restore to pre-execution state:

```python
manifest_path = "/data/reports/job-uuid_manifest.json"
success = await engine.rollback(manifest_path)
```

## Execution Flow

The engine executes operations in this specific order:

1. **Validate** - Check prerequisites and execution plan
2. **Clear** - Clean working directory
3. **Create Directories** - Build folder structure (parents first)
4. **Process Files** - Copy/move/rename all files
5. **Create Shortcuts** - Link duplicate files to primary
6. **Setup Archives** - Organize version history
7. **Generate Manifest** - Create audit trail
8. **Update Database** - Record final states

## Safety Features

### Source Protection
- **Never modifies `/data/source/`** - all operations target `/data/working/`
- Source files remain pristine for rollback

### Validation
- Pre-execution checks for:
  - Source file existence
  - Path conflicts
  - Invalid filename characters
  - Circular references

### Error Handling
- Continues processing on individual file errors
- Tracks all failures in manifest
- Database transaction rollback on critical errors
- Comprehensive error logging with stack traces

### Filename Sanitization
- Removes invalid characters: `< > : " / \ | ? *`
- Handles Windows reserved names (CON, PRN, AUX, etc.)
- Strips leading/trailing spaces and dots
- Ensures cross-platform compatibility

## Database Integration

### Input Tables
- `document_items` - File assignments and proposed changes
- `directory_structure` - Planned folder hierarchy
- `duplicate_groups` / `duplicate_members` - Shortcut plans
- `version_chains` / `version_chain_members` - Archive plans

### Output Tables
- `execution_log` - Detailed operation tracking
- `shortcut_files` - Created shortcuts for rollback
- `processing_jobs` - Job-level statistics

### Updated Fields
- `document_items.final_name` - Actual filename after execution
- `document_items.final_path` - Actual path after execution
- `document_items.status` - Updated to 'applied'
- `document_items.changes_applied` - Set to TRUE

## Shortcut Types

The engine supports multiple shortcut types with automatic fallback:

| Type | Platform | Description |
|------|----------|-------------|
| **Symlink** | Linux/Mac | Native OS symlinks (preferred) |
| **.url** | All | Internet Shortcut format (fallback) |
| **.desktop** | Linux | Desktop Entry files |

Auto strategy: Try symlink → Fall back to .url if symlink fails

### Shortcut Examples

**Symlink** (Linux/Mac):
```bash
$ ls -l
lrwxrwxrwx  1 user user  45 Jan 22 10:00 duplicate.pdf -> ../primary/document.pdf
```

**.url file** (Cross-platform):
```ini
[InternetShortcut]
URL=file:///data/working/primary/document.pdf
```

**.desktop file** (Linux):
```ini
[Desktop Entry]
Type=Link
Name=document.pdf
URL=file:///data/working/primary/document.pdf
```

## Version Archives

For documents with version chains:

1. Creates archive directory (e.g., `_versions/Budget_Report/`)
2. Copies superseded versions with version names
3. Keeps current version in main location
4. Generates `_version_history.json` manifest

### Version History JSON

```json
{
  "document_name": "Budget Report",
  "current_version": 3,
  "current_file": "../Budget_Report.xlsx",
  "archive_path": "/Documents/Finance/_versions/Budget_Report/",
  "archive_strategy": "subfolder",
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
```

## Execution Manifest

Generated at `/data/reports/{job_id}_manifest.json`:

```json
{
  "job_id": "uuid",
  "executed_at": "2024-01-22T10:30:00Z",
  "source_zip": "original.zip",
  "statistics": {
    "total_files": 500,
    "directories_created": 25,
    "files_copied": 480,
    "files_renamed": 200,
    "files_moved": 150,
    "shortcuts_created": 20,
    "version_archives": 15,
    "errors": 2
  },
  "operations": [
    {
      "type": "copy",
      "source": "/data/source/old/path/file.docx",
      "target": "/data/working/new/path/renamed.docx",
      "document_id": 123,
      "success": true,
      "timestamp": "2024-01-22T10:30:05Z"
    }
  ],
  "shortcuts": [
    {
      "shortcut_path": "/data/working/path/duplicate.url",
      "target_path": "/data/working/primary/file.docx",
      "original_path": "/data/source/duplicate/file.docx",
      "shortcut_type": "url",
      "created_at": "2024-01-22T10:30:10Z"
    }
  ],
  "errors": [
    {
      "document_id": 456,
      "error": "Permission denied",
      "source": "/data/source/locked/file.docx",
      "operation": "copy",
      "timestamp": "2024-01-22T10:30:15Z"
    }
  ]
}
```

## Progress Tracking

The engine reports progress throughout execution:

- 5% - Plan validated
- 10% - Working directory cleared
- 20% - Directories created
- 70% - Files processed
- 85% - Shortcuts created
- 90% - Version archives setup
- 95% - Manifest generated
- 100% - Database updated

Progress is visible in:
- `processing_jobs.progress_percent`
- `processing_jobs.current_phase`
- Structured logs

## Performance

### Optimization Strategies
- Sequential directory creation (sorted by depth)
- Parallel file operations (future enhancement)
- Efficient database queries with indexes
- Streaming manifest generation

### Resource Usage
- Memory: O(1) for operations, O(n) for manifest
- Disk: 2x source size (source + working)
- Database: Bulk updates where possible

## Error Recovery

### Partial Execution
If execution fails mid-way:
- Already-completed operations remain
- Manifest shows what succeeded/failed
- Can resume or rollback

### Rollback Process
1. Load manifest to see what was done
2. Clear working directory
3. Reset database states
4. User can re-run from organization phase

## Testing

### Manual Testing

```bash
# 1. Setup test data
mkdir -p /data/source/test
echo "content" > /data/source/test/file.txt

# 2. Create test job in database
psql -c "INSERT INTO processing_jobs (id, source_path) VALUES ('test-uuid', '/data/source/test')"

# 3. Run execution engine
python -c "
import asyncio
from src.execution import ExecutionEngine

async def test():
    engine = ExecutionEngine(job_id='test-uuid')
    result = await engine.run(dry_run=True)
    print(result.to_dict())

asyncio.run(test())
"
```

### Integration Testing

The execution engine integrates with:
- Index Agent (reads indexed files)
- Dedup Agent (creates shortcuts)
- Version Agent (organizes archives)
- Organize Agent (executes plans)

## Configuration

Settings from `config.py`:

```python
data_source_path: str = "/data/source"      # Never modified
data_working_path: str = "/data/working"    # Execution target
data_reports_path: str = "/data/reports"    # Manifest output
dry_run: bool = False                       # Preview mode
```

## Logging

Structured logging with contextual information:

```python
logger.info(
    "file_copied",
    source="/data/source/file.txt",
    target="/data/working/new/file.txt",
    size_bytes=1024,
    document_id=123
)
```

Log levels:
- **INFO**: Normal operations
- **WARNING**: Non-fatal issues (e.g., skipped files)
- **ERROR**: Operation failures with full context
- **DEBUG**: Detailed progress (if enabled)

## Future Enhancements

1. **Parallel File Operations** - Process files concurrently
2. **Resume Capability** - Continue from last checkpoint
3. **Incremental Execution** - Only execute changed files
4. **Compression** - Compress archives automatically
5. **Verification** - Hash validation after copy
6. **Deduplication** - Hardlink identical files
7. **Cloud Integration** - Execute to cloud storage

## Related Documentation

- [Base Agent](../agents/base_agent.py) - Agent framework
- [Configuration](../config.py) - Settings management
- [Database Schema](../../database/init.sql) - Data model
- [Architecture](../../ARCHITECTURE.md) - System design
