# Document Organizer v2 - Containerized Architecture

## Overview

A Docker-based document organization system that:

1. **Downloads** entire directory as ZIP from OneDrive/SharePoint
1. **Mounts** extracted files as a Docker volume for local processing
1. **Analyzes** content with Ollama (local, no API limits)
1. **Detects duplicates** via content hashing + LLM decision-making
1. **Identifies versions** of documents and applies version control logic
1. **Reorganizes** files locally with full rollback capability
1. **Re-zips** and uploads back when approved

## Why This Approach?

|Aspect             |API-Based (v1)           |Container-Based (v2)      |
|-------------------|-------------------------|--------------------------|
|Speed              |Slow (API calls per file)|Fast (local filesystem)   |
|Rate Limits        |MS Graph throttling      |None                      |
|Rollback           |Complex (undo API calls) |Simple (keep original ZIP)|
|Duplicate Detection|Hash comparison via API  |Direct file comparison    |
|Cost               |API calls + bandwidth    |One download + upload     |
|Reliability        |Network-dependent        |Local processing          |

-----

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        Document Organizer v2 Pipeline                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────┐     ┌─────────────────────────────────────────────────────┐    │
│  │ OneDrive/   │────▶│                 DOCKER CONTAINER                    │    │
│  │ SharePoint  │     │  ┌─────────────────────────────────────────────┐   │    │
│  │             │     │  │           PROCESSING PIPELINE                │   │    │
│  │  Download   │     │  │                                              │   │    │
│  │  as ZIP     │     │  │  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────────┐ │   │    │
│  └─────────────┘     │  │  │Index │─▶│Dedup │─▶│Version│─▶│Organize  │ │   │    │
│                      │  │  │Agent │  │Agent │  │Agent  │  │Agent     │ │   │    │
│                      │  │  └──────┘  └──────┘  └──────┘  └──────────┘ │   │    │
│  ┌─────────────┐     │  │      │          │         │          │      │   │    │
│  │ OneDrive/   │◀────│  │      ▼          ▼         ▼          ▼      │   │    │
│  │ SharePoint  │     │  │  ┌──────────────────────────────────────┐   │   │    │
│  │             │     │  │  │         PostgreSQL Database          │   │   │    │
│  │  Upload     │     │  │  └──────────────────────────────────────┘   │   │    │
│  │  Result ZIP │     │  │                                              │   │    │
│  └─────────────┘     │  └─────────────────────────────────────────────┘   │    │
│                      │                                                     │    │
│                      │  Volumes:                                           │    │
│                      │  ├── /data/source    (original extracted files)    │    │
│                      │  ├── /data/working   (reorganized structure)       │    │
│                      │  ├── /data/output    (final ZIP for upload)        │    │
│                      │  └── /data/postgres  (database persistence)        │    │
│                      │                                                     │    │
│                      │  Services:                                          │    │
│                      │  ├── ollama          (local LLM)                   │    │
│                      │  ├── postgres        (metadata + decisions)        │    │
│                      │  └── processor       (Python orchestration)        │    │
│                      └─────────────────────────────────────────────────────┘    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

-----

## Processing Agents

### Agent 1: Index Agent

**Purpose**: Crawl the extracted directory and build initial inventory

**Operations**:

- Walk directory tree
- Calculate SHA256 hash for each file
- Extract metadata (size, dates, extension)
- Store in `document_items` table

**Output**: Complete inventory with content hashes

-----

### Agent 2: Duplicate Detection Agent

**Purpose**: Find duplicate files and decide how to handle them

**Logic Flow**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      DUPLICATE DETECTION LOGIC                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. GROUP BY content_hash WHERE count > 1                                   │
│                                                                              │
│  2. For each duplicate group:                                               │
│     ┌────────────────────────────────────────────────────────────────────┐  │
│     │ EXACT DUPLICATES (same hash)                                       │  │
│     │                                                                    │  │
│     │  • Compare file paths and names                                   │  │
│     │  • Compare modification dates                                     │  │
│     │  • Identify "primary" location (most logical path)                │  │
│     │                                                                    │  │
│     │  LLM Decision Prompt:                                             │  │
│     │  "These files are byte-identical duplicates:                      │  │
│     │   - /Projects/Alpha/report.docx (modified 2024-01-15)            │  │
│     │   - /Archive/Old/report_backup.docx (modified 2024-01-10)        │  │
│     │   - /Shared/Team/report_copy.docx (modified 2024-01-15)          │  │
│     │                                                                    │  │
│     │   Based on paths and dates, which should be PRIMARY?              │  │
│     │   Should others be: SHORTCUT, KEEP_BOTH, or DELETE?               │  │
│     │   Consider: backup purposes, shared access needs, archive value"  │  │
│     └────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  3. Record decisions in `duplicate_groups` table                            │
│                                                                              │
│  4. Actions:                                                                 │
│     • PRIMARY: Keep as-is, may be renamed/moved by Organize Agent          │
│     • SHORTCUT: Replace with .lnk/.url pointing to primary                 │
│     • KEEP_BOTH: Legitimate copies (e.g., template in multiple locations)  │
│     • DELETE: Remove (only with explicit approval)                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Shortcut Strategy**:

- Windows: Create `.lnk` files (requires `pylnk3` or similar)
- Cross-platform: Create `.url` files or symbolic links
- Store original location in metadata for potential restoration

-----

### Agent 3: Version Control Agent

**Purpose**: Identify document versions and establish version control

**Version Detection Strategies**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      VERSION DETECTION LOGIC                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  DETECTION METHODS (in order of confidence):                                │
│                                                                              │
│  1. EXPLICIT VERSION MARKERS (High Confidence)                              │
│     Pattern matches:                                                         │
│     • report_v1.docx, report_v2.docx, report_v3.docx                       │
│     • document_draft.docx, document_final.docx                             │
│     • file_2024-01-01.xlsx, file_2024-02-15.xlsx                          │
│     • proposal (1).docx, proposal (2).docx                                 │
│     • report_rev1.pdf, report_rev2.pdf                                     │
│                                                                              │
│  2. SIMILAR NAMES + DIFFERENT HASHES (Medium Confidence)                    │
│     • Base name similarity > 80% (Levenshtein)                             │
│     • Same extension                                                        │
│     • Different content hash                                                │
│     • LLM confirms relationship via content comparison                      │
│                                                                              │
│  3. CONTENT SIMILARITY (Lower Confidence - Optional)                        │
│     • Extract text, compute similarity score                                │
│     • High similarity + different dates = likely versions                   │
│     • Requires LLM to confirm and determine order                          │
│                                                                              │
│  VERSION CHAIN ESTABLISHMENT:                                               │
│                                                                              │
│  For each version group, determine:                                         │
│  • Version order (v1 → v2 → v3 or by date)                                 │
│  • Which is CURRENT (latest approved version)                              │
│  • Which are SUPERSEDED (older versions to archive)                        │
│  • Naming convention to apply                                               │
│                                                                              │
│  LLM Decision Prompt:                                                       │
│  "These files appear to be versions of the same document:                   │
│   - budget_draft.xlsx (2024-01-10, 45KB) [summary: Q1 budget draft...]     │
│   - budget_v2.xlsx (2024-01-20, 52KB) [summary: Q1 budget with updates...] │
│   - budget_final.xlsx (2024-02-01, 58KB) [summary: Approved Q1 budget...]  │
│                                                                              │
│   Confirm version order and identify:                                       │
│   1. CURRENT version (the authoritative one)                               │
│   2. Version chain for naming (e.g., _v1, _v2, _v3)                        │
│   3. Should superseded versions be archived or kept alongside?"            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Version Control Naming Schema**:

```
CURRENT VERSION:
  /Documents/Projects/Alpha/Budget_Q1_2024.xlsx           (no version suffix)

ARCHIVED VERSIONS:
  /Documents/Projects/Alpha/_versions/Budget_Q1_2024/
    ├── Budget_Q1_2024_v1_2024-01-10.xlsx
    ├── Budget_Q1_2024_v2_2024-01-20.xlsx
    └── _version_history.json                              (metadata)

VERSION HISTORY JSON:
{
  "document_id": "abc123",
  "current_version": 3,
  "current_file": "../Budget_Q1_2024.xlsx",
  "versions": [
    {"version": 1, "date": "2024-01-10", "file": "Budget_Q1_2024_v1_2024-01-10.xlsx", "status": "superseded"},
    {"version": 2, "date": "2024-01-20", "file": "Budget_Q1_2024_v2_2024-01-20.xlsx", "status": "superseded"},
    {"version": 3, "date": "2024-02-01", "file": "../Budget_Q1_2024.xlsx", "status": "current"}
  ]
}
```

-----

### Agent 4: Organization Agent

**Purpose**: Apply naming schemas, tags, and directory structure

**Operates on**:

- Primary files (not duplicates marked for shortcut)
- Current versions (superseded versions handled by Version Agent)
- Files not in version chains

**Same logic as v1 but**:

- Works on local filesystem (fast)
- Respects decisions from Dedup and Version agents
- Creates actual directory structure
- Moves/renames files in `/data/working`

-----

## Database Schema Additions

```sql
-- =============================================================================
-- DUPLICATE GROUPS
-- Tracks groups of identical files and decisions
-- =============================================================================

CREATE TABLE duplicate_groups (
    id SERIAL PRIMARY KEY,
    content_hash VARCHAR(64) NOT NULL,
    file_count INTEGER NOT NULL,
    total_size_bytes BIGINT,
    
    -- Decision
    primary_document_id INTEGER REFERENCES document_items(id),
    decision_reasoning TEXT,
    decided_at TIMESTAMPTZ,
    decided_by VARCHAR(50),  -- 'auto', 'llm', 'user'
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_duplicate_groups_hash ON duplicate_groups(content_hash);


-- =============================================================================
-- DUPLICATE MEMBERS
-- Links documents to their duplicate group
-- =============================================================================

CREATE TABLE duplicate_members (
    id SERIAL PRIMARY KEY,
    group_id INTEGER REFERENCES duplicate_groups(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES document_items(id),
    
    -- Role in the group
    is_primary BOOLEAN DEFAULT FALSE,
    action VARCHAR(50) NOT NULL,  -- 'keep_primary', 'shortcut', 'keep_both', 'delete'
    action_reasoning TEXT,
    
    -- Shortcut details (if action = 'shortcut')
    shortcut_target_path TEXT,
    shortcut_created BOOLEAN DEFAULT FALSE,
    
    CONSTRAINT valid_action CHECK (action IN ('keep_primary', 'shortcut', 'keep_both', 'delete'))
);

CREATE INDEX idx_duplicate_members_group ON duplicate_members(group_id);
CREATE INDEX idx_duplicate_members_document ON duplicate_members(document_id);


-- =============================================================================
-- VERSION CHAINS
-- Groups of documents that are versions of each other
-- =============================================================================

CREATE TABLE version_chains (
    id SERIAL PRIMARY KEY,
    chain_name VARCHAR(255) NOT NULL,  -- Base document name
    base_path TEXT,  -- Common path prefix
    
    -- Current version reference
    current_document_id INTEGER REFERENCES document_items(id),
    current_version_number INTEGER,
    
    -- Detection metadata
    detection_method VARCHAR(50),  -- 'explicit_marker', 'name_similarity', 'content_similarity'
    detection_confidence DECIMAL(3,2),  -- 0.00 to 1.00
    
    -- LLM decision
    llm_reasoning TEXT,
    version_order_confirmed BOOLEAN DEFAULT FALSE,
    
    -- Archive strategy
    archive_strategy VARCHAR(50) DEFAULT 'subfolder',  -- 'subfolder', 'inline', 'separate_archive'
    archive_path TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_version_chains_current ON version_chains(current_document_id);


-- =============================================================================
-- VERSION CHAIN MEMBERS
-- Individual versions within a chain
-- =============================================================================

CREATE TABLE version_chain_members (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER REFERENCES version_chains(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES document_items(id),
    
    -- Version info
    version_number INTEGER NOT NULL,
    version_label VARCHAR(50),  -- 'v1', 'draft', 'final', etc.
    version_date DATE,
    
    -- Status
    is_current BOOLEAN DEFAULT FALSE,
    status VARCHAR(50) DEFAULT 'active',  -- 'active', 'superseded', 'archived'
    
    -- Naming
    proposed_version_name VARCHAR(500),  -- New name following version schema
    proposed_version_path TEXT,
    
    CONSTRAINT valid_version_status CHECK (status IN ('active', 'superseded', 'archived')),
    CONSTRAINT unique_current_per_chain UNIQUE (chain_id, is_current) WHERE is_current = TRUE
);

CREATE INDEX idx_version_members_chain ON version_chain_members(chain_id);
CREATE INDEX idx_version_members_document ON version_chain_members(document_id);


-- =============================================================================
-- SHORTCUT FILES
-- Track created shortcuts for restoration capability
-- =============================================================================

CREATE TABLE shortcut_files (
    id SERIAL PRIMARY KEY,
    original_document_id INTEGER REFERENCES document_items(id),
    shortcut_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    shortcut_type VARCHAR(20) NOT NULL,  -- 'lnk', 'url', 'symlink'
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- For restoration
    original_path TEXT NOT NULL,
    original_hash VARCHAR(64)
);


-- =============================================================================
-- PROCESSING JOBS
-- Track container processing jobs
-- =============================================================================

CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Source
    source_type VARCHAR(50) NOT NULL,  -- 'onedrive', 'sharepoint', 'local'
    source_path TEXT NOT NULL,
    source_zip_path TEXT,
    source_zip_hash VARCHAR(64),
    source_file_count INTEGER,
    source_total_size BIGINT,
    
    -- Status
    status VARCHAR(50) DEFAULT 'pending',
    current_phase VARCHAR(50),  -- 'downloading', 'indexing', 'deduplicating', 'versioning', 'organizing', 'packaging', 'uploading'
    
    -- Progress
    progress_percent INTEGER DEFAULT 0,
    files_processed INTEGER DEFAULT 0,
    
    -- Results
    duplicates_found INTEGER DEFAULT 0,
    shortcuts_created INTEGER DEFAULT 0,
    version_chains_found INTEGER DEFAULT 0,
    files_renamed INTEGER DEFAULT 0,
    files_moved INTEGER DEFAULT 0,
    
    -- Output
    output_zip_path TEXT,
    output_zip_hash VARCHAR(64),
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- Error handling
    error_message TEXT,
    
    CONSTRAINT valid_job_status CHECK (status IN (
        'pending', 'downloading', 'processing', 'review_required', 
        'approved', 'packaging', 'uploading', 'completed', 'failed', 'cancelled'
    ))
);
```

-----

## Processing Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COMPLETE PROCESSING FLOW                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1: ACQUISITION                                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. n8n workflow downloads folder as ZIP from OneDrive/SharePoint       │ │
│  │ 2. ZIP placed in /data/input volume                                    │ │
│  │ 3. Container extracts to /data/source                                  │ │
│  │ 4. Create processing_job record                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  PHASE 2: INDEXING (Index Agent)                                            │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. Walk /data/source directory tree                                    │ │
│  │ 2. For each file:                                                      │ │
│  │    • Calculate SHA256 hash                                             │ │
│  │    • Extract metadata (size, dates, mime type)                         │ │
│  │    • Extract text content (for supported types)                        │ │
│  │    • Generate summary with Ollama                                      │ │
│  │ 3. Store all in document_items                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  PHASE 3: DUPLICATE DETECTION (Dedup Agent)                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. Query: GROUP BY content_hash HAVING count > 1                       │ │
│  │ 2. For each duplicate group:                                           │ │
│  │    • Analyze paths, dates, names                                       │ │
│  │    • Ask LLM for decision (primary vs shortcut vs keep)                │ │
│  │    • Record in duplicate_groups + duplicate_members                    │ │
│  │ 3. Mark documents with duplicate_action                                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  PHASE 4: VERSION DETECTION (Version Agent)                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. Pattern matching for version markers (v1, v2, draft, final, dates)  │ │
│  │ 2. Name similarity analysis for potential versions                     │ │
│  │ 3. For each potential version chain:                                   │ │
│  │    • Compare content summaries                                         │ │
│  │    • Ask LLM to confirm version relationship and order                 │ │
│  │    • Identify current vs superseded                                    │ │
│  │ 4. Record in version_chains + version_chain_members                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  PHASE 5: ORGANIZATION (Organization Agent)                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. Exclude: duplicates (shortcut), superseded versions                 │ │
│  │ 2. Send remaining files to Claude for organization plan                │ │
│  │ 3. Generate:                                                           │ │
│  │    • Naming schemas                                                    │ │
│  │    • Tag taxonomy                                                      │ │
│  │    • Directory structure                                               │ │
│  │ 4. Assign each file to new location                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  PHASE 6: REVIEW (Optional - if configured)                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. Generate review report (JSON + HTML)                                │ │
│  │ 2. Wait for user approval via n8n webhook or manual trigger            │ │
│  │ 3. Allow modifications to plan                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  PHASE 7: EXECUTION                                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. Create /data/working directory structure                            │ │
│  │ 2. Copy/move files to new locations with new names                     │ │
│  │ 3. Create _versions/ folders for version chains                        │ │
│  │ 4. Create shortcut files for duplicates                                │ │
│  │ 5. Generate _version_history.json files                                │ │
│  │ 6. Create _organization_manifest.json (full audit)                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  PHASE 8: PACKAGING                                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. ZIP /data/working to /data/output                                   │ │
│  │ 2. Calculate output hash                                               │ │
│  │ 3. Generate summary report                                             │ │
│  │ 4. Trigger n8n to upload back to OneDrive/SharePoint                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

-----

## Container Structure

```
document-organizer/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
│
├── src/
│   ├── __init__.py
│   ├── main.py                    # Orchestrator
│   ├── config.py                  # Configuration management
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py          # Abstract base class
│   │   ├── index_agent.py         # File discovery + hashing
│   │   ├── dedup_agent.py         # Duplicate detection
│   │   ├── version_agent.py       # Version control
│   │   └── organize_agent.py      # Naming + structure
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ollama_service.py      # Ollama API wrapper
│   │   ├── claude_service.py      # Claude API wrapper
│   │   ├── database_service.py    # PostgreSQL operations
│   │   ├── file_service.py        # File operations
│   │   └── shortcut_service.py    # Create shortcuts/links
│   │
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── base_extractor.py
│   │   ├── pdf_extractor.py
│   │   ├── docx_extractor.py
│   │   ├── xlsx_extractor.py
│   │   └── text_extractor.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── hashing.py             # SHA256 utilities
│       ├── naming.py              # Name similarity, pattern matching
│       └── reporting.py           # Generate reports
│
├── database/
│   └── init.sql                   # Schema initialization
│
├── n8n/
│   ├── workflow_download.json     # Download ZIP from cloud
│   ├── workflow_trigger.json      # Trigger container processing
│   ├── workflow_upload.json       # Upload result ZIP
│   └── workflow_webhook.json      # Receive completion callback
│
└── data/                          # Docker volume mount point
    ├── input/                     # Downloaded ZIPs
    ├── source/                    # Extracted original files
    ├── working/                   # Reorganized structure
    ├── output/                    # Final ZIPs for upload
    └── reports/                   # Processing reports
```

-----

## Key Decisions & Trade-offs

### Duplicate Handling

|Strategy     |When to Use                                                 |
|-------------|------------------------------------------------------------|
|**SHORTCUT** |Default for exact duplicates - saves space, maintains access|
|**KEEP_BOTH**|Templates, intentionally distributed files                  |
|**DELETE**   |Only with explicit user approval, after review phase        |

### Version Control

|Strategy            |When to Use                                           |
|--------------------|------------------------------------------------------|
|**Subfolder**       |Default - keeps versions near current, easy browsing  |
|**Inline**          |Small teams, few versions - versions alongside current|
|**Separate Archive**|Large collections - centralized version archive       |

### LLM Usage

|Agent   |Ollama (Local)       |Claude (API)                            |
|--------|---------------------|----------------------------------------|
|Index   |Content summarization|-                                       |
|Dedup   |Simple decisions     |Complex multi-file decisions            |
|Version |Pattern confirmation |Version order, relationship confirmation|
|Organize|-                    |Full organization planning              |

-----

## Safety Features

1. **Original Preservation**: Source ZIP kept untouched until upload confirmed
1. **Manifest Tracking**: Complete audit trail in `_organization_manifest.json`
1. **Review Phase**: Optional human approval before execution
1. **Rollback Data**: All original paths stored for potential restoration
1. **Shortcut Metadata**: Original file info preserved in shortcut records

-----

## Next Steps

1. Create Docker container setup
1. Implement base agent framework
1. Build Index Agent
1. Build Dedup Agent
1. Build Version Agent
1. Build Organization Agent
1. Create n8n workflows for download/upload
1. Integration testing
1. Documentation
