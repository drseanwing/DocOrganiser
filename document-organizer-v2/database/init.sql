-- =============================================================================
-- Document Organizer v2 - Complete Database Schema
-- =============================================================================
-- Run this on PostgreSQL 14+ to create all required tables, indexes, and functions
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text similarity

-- =============================================================================
-- PROCESSING JOBS
-- Master record for each processing run
-- =============================================================================

CREATE TABLE IF NOT EXISTS processing_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Source information
    source_type VARCHAR(50) NOT NULL,              -- 'onedrive', 'sharepoint', 'local'
    source_path TEXT NOT NULL,
    source_zip_path TEXT,
    source_zip_hash VARCHAR(64),
    source_file_count INTEGER,
    source_total_size BIGINT,
    
    -- Status tracking
    status VARCHAR(50) DEFAULT 'pending',
    current_phase VARCHAR(50),
    progress_percent INTEGER DEFAULT 0,
    files_processed INTEGER DEFAULT 0,
    
    -- Results summary
    duplicates_found INTEGER DEFAULT 0,
    shortcuts_created INTEGER DEFAULT 0,
    version_chains_found INTEGER DEFAULT 0,
    files_renamed INTEGER DEFAULT 0,
    files_moved INTEGER DEFAULT 0,
    
    -- Output
    output_zip_path TEXT,
    output_zip_hash VARCHAR(64),
    output_uploaded BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- Error handling
    error_message TEXT,
    
    CONSTRAINT valid_job_status CHECK (status IN (
        'pending', 'downloading', 'extracting', 'processing', 
        'review_required', 'approved', 'executing', 'packaging', 
        'uploading', 'completed', 'failed', 'cancelled'
    ))
);

CREATE INDEX idx_processing_jobs_status ON processing_jobs(status);
CREATE INDEX idx_processing_jobs_created ON processing_jobs(created_at DESC);

-- =============================================================================
-- DOCUMENT ITEMS
-- Main inventory of all files being processed
-- =============================================================================

CREATE TABLE IF NOT EXISTS document_items (
    id SERIAL PRIMARY KEY,
    
    -- Identifiers
    file_id VARCHAR(255) NOT NULL UNIQUE,          -- Hash of path or OneDrive ID
    job_id UUID REFERENCES processing_jobs(id),
    
    -- Current state (from source)
    current_name VARCHAR(500) NOT NULL,
    current_path TEXT NOT NULL,
    current_extension VARCHAR(50),
    file_size_bytes BIGINT,
    mime_type VARCHAR(255),
    content_hash VARCHAR(64),                       -- SHA256 of content
    
    -- Source metadata
    source_created_at TIMESTAMPTZ,
    source_modified_at TIMESTAMPTZ,
    e_tag VARCHAR(255),
    
    -- Content analysis (from Ollama)
    content_summary TEXT,
    document_type VARCHAR(100),
    key_topics TEXT[],
    content_context TEXT,                           -- Sibling context used
    token_count INTEGER,
    ollama_model VARCHAR(100),
    
    -- Proposed changes (from Claude)
    proposed_name VARCHAR(500),
    proposed_path TEXT,
    proposed_tags TEXT[],
    organization_reasoning TEXT,
    organization_batch_id UUID,
    
    -- Final state (after execution)
    final_name VARCHAR(500),
    final_path TEXT,
    final_file_id VARCHAR(255),
    changes_applied BOOLEAN DEFAULT FALSE,
    apply_error TEXT,
    
    -- Computed columns for change detection
    has_name_change BOOLEAN GENERATED ALWAYS AS (
        proposed_name IS NOT NULL AND proposed_name != current_name
    ) STORED,
    has_path_change BOOLEAN GENERATED ALWAYS AS (
        proposed_path IS NOT NULL AND proposed_path != current_path
    ) STORED,
    
    -- Status tracking
    status VARCHAR(50) DEFAULT 'discovered',
    is_deleted BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    crawled_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    organized_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ,
    
    -- Batch tracking
    crawl_batch_id UUID,
    process_batch_id UUID,
    apply_batch_id UUID,
    
    CONSTRAINT valid_doc_status CHECK (status IN (
        'discovered', 'processing', 'processed', 
        'organizing', 'organized', 'pending_apply',
        'applying', 'applied', 'error', 'skipped'
    ))
);

-- Indexes for document_items
CREATE INDEX idx_documents_status ON document_items(status);
CREATE INDEX idx_documents_hash ON document_items(content_hash);
CREATE INDEX idx_documents_path ON document_items(current_path);
CREATE INDEX idx_documents_extension ON document_items(current_extension);
CREATE INDEX idx_documents_job ON document_items(job_id);
CREATE INDEX idx_documents_changes ON document_items(has_name_change, has_path_change) 
    WHERE has_name_change = TRUE OR has_path_change = TRUE;
CREATE INDEX idx_documents_summary_search ON document_items 
    USING gin(to_tsvector('english', content_summary));

-- =============================================================================
-- DUPLICATE DETECTION
-- =============================================================================

CREATE TABLE IF NOT EXISTS duplicate_groups (
    id SERIAL PRIMARY KEY,
    content_hash VARCHAR(64) NOT NULL UNIQUE,
    file_count INTEGER NOT NULL,
    total_size_bytes BIGINT,
    
    -- Decision
    primary_document_id INTEGER REFERENCES document_items(id),
    decision_reasoning TEXT,
    decided_at TIMESTAMPTZ,
    decided_by VARCHAR(50),                         -- 'auto', 'llm', 'user'
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_duplicate_groups_hash ON duplicate_groups(content_hash);

CREATE TABLE IF NOT EXISTS duplicate_members (
    id SERIAL PRIMARY KEY,
    group_id INTEGER REFERENCES duplicate_groups(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES document_items(id),
    
    -- Role and action
    is_primary BOOLEAN DEFAULT FALSE,
    action VARCHAR(50) NOT NULL,                    -- 'keep_primary', 'shortcut', 'keep_both', 'delete'
    action_reasoning TEXT,
    
    -- Shortcut details
    shortcut_target_path TEXT,
    shortcut_created BOOLEAN DEFAULT FALSE,
    
    CONSTRAINT valid_dup_action CHECK (action IN ('keep_primary', 'shortcut', 'keep_both', 'delete')),
    CONSTRAINT unique_group_document UNIQUE (group_id, document_id)
);

CREATE INDEX idx_duplicate_members_group ON duplicate_members(group_id);
CREATE INDEX idx_duplicate_members_document ON duplicate_members(document_id);
CREATE INDEX idx_duplicate_members_action ON duplicate_members(action);

-- =============================================================================
-- VERSION CONTROL
-- =============================================================================

CREATE TABLE IF NOT EXISTS version_chains (
    id SERIAL PRIMARY KEY,
    chain_name VARCHAR(255) NOT NULL,
    base_path TEXT,
    
    -- Current version
    current_document_id INTEGER REFERENCES document_items(id),
    current_version_number INTEGER,
    
    -- Detection
    detection_method VARCHAR(50),                   -- 'explicit_marker', 'name_similarity', 'content_similarity'
    detection_confidence DECIMAL(3,2),
    llm_reasoning TEXT,
    version_order_confirmed BOOLEAN DEFAULT FALSE,
    
    -- Archive configuration
    archive_strategy VARCHAR(50) DEFAULT 'subfolder',
    archive_path TEXT,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_version_chains_current ON version_chains(current_document_id);
CREATE INDEX idx_version_chains_name ON version_chains(chain_name);

CREATE TABLE IF NOT EXISTS version_chain_members (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER REFERENCES version_chains(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES document_items(id),
    
    -- Version info
    version_number INTEGER NOT NULL,
    version_label VARCHAR(50),
    version_date DATE,
    
    -- Status
    is_current BOOLEAN DEFAULT FALSE,
    status VARCHAR(50) DEFAULT 'active',
    
    -- Proposed naming
    proposed_version_name VARCHAR(500),
    proposed_version_path TEXT,
    
    CONSTRAINT valid_version_status CHECK (status IN ('active', 'superseded', 'archived'))
);

CREATE INDEX idx_version_members_chain ON version_chain_members(chain_id);
CREATE INDEX idx_version_members_document ON version_chain_members(document_id);
CREATE INDEX idx_version_members_current ON version_chain_members(is_current) WHERE is_current = TRUE;

-- =============================================================================
-- ORGANIZATION PLANNING
-- =============================================================================

CREATE TABLE IF NOT EXISTS naming_schema (
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

CREATE UNIQUE INDEX idx_naming_schema_active ON naming_schema(document_type) 
    WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS tag_taxonomy (
    id SERIAL PRIMARY KEY,
    tag_name VARCHAR(100) NOT NULL UNIQUE,
    parent_tag_id INTEGER REFERENCES tag_taxonomy(id),
    description TEXT,
    color VARCHAR(7),
    usage_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tag_taxonomy_parent ON tag_taxonomy(parent_tag_id);
CREATE INDEX idx_tag_taxonomy_name ON tag_taxonomy(tag_name);

CREATE TABLE IF NOT EXISTS directory_structure (
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

CREATE INDEX idx_directory_structure_path ON directory_structure(path);
CREATE INDEX idx_directory_structure_depth ON directory_structure(depth);

-- =============================================================================
-- EXECUTION TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS shortcut_files (
    id SERIAL PRIMARY KEY,
    original_document_id INTEGER REFERENCES document_items(id),
    shortcut_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    shortcut_type VARCHAR(20) NOT NULL,             -- 'symlink', 'url', 'lnk', 'desktop'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- For restoration
    original_path TEXT NOT NULL,
    original_hash VARCHAR(64)
);

CREATE INDEX idx_shortcut_files_document ON shortcut_files(original_document_id);

CREATE TABLE IF NOT EXISTS execution_log (
    id SERIAL PRIMARY KEY,
    job_id UUID REFERENCES processing_jobs(id),
    operation VARCHAR(50) NOT NULL,                 -- 'create_dir', 'copy_file', 'rename', 'move', 'create_shortcut'
    source_path TEXT,
    target_path TEXT,
    document_id INTEGER REFERENCES document_items(id),
    success BOOLEAN NOT NULL,
    error_message TEXT,
    duration_ms INTEGER,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_execution_log_job ON execution_log(job_id);
CREATE INDEX idx_execution_log_operation ON execution_log(operation);
CREATE INDEX idx_execution_log_success ON execution_log(success) WHERE success = FALSE;

-- =============================================================================
-- PROCESSING LOG (Audit Trail)
-- =============================================================================

CREATE TABLE IF NOT EXISTS processing_log (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES document_items(id),
    batch_id UUID,
    action VARCHAR(100) NOT NULL,
    phase VARCHAR(50),
    details JSONB,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_processing_log_batch ON processing_log(batch_id);
CREATE INDEX idx_processing_log_document ON processing_log(document_id);
CREATE INDEX idx_processing_log_action ON processing_log(action);
CREATE INDEX idx_processing_log_created ON processing_log(created_at DESC);

-- =============================================================================
-- SYSTEM CONFIGURATION
-- =============================================================================

CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default configuration
INSERT INTO system_config (key, value, description) VALUES
    ('test_mode', 'true', 'When true, execution generates reports without making changes'),
    ('batch_size', '50', 'Number of files to process per batch'),
    ('context_depth', '5', 'Number of sibling file summaries to include'),
    ('max_file_size_mb', '100', 'Maximum file size to process'),
    ('ollama_model', 'llama3.2', 'Ollama model for content analysis'),
    ('claude_model', 'claude-sonnet-4-20250514', 'Claude model for organization planning'),
    ('version_archive_strategy', 'subfolder', 'How to archive superseded versions'),
    ('review_required', 'true', 'Require human review before execution'),
    ('auto_approve_shortcuts', 'false', 'Automatically approve shortcut creation')
ON CONFLICT (key) DO NOTHING;

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Get configuration value
CREATE OR REPLACE FUNCTION get_config(config_key VARCHAR) 
RETURNS TEXT AS $$
    SELECT value FROM system_config WHERE key = config_key;
$$ LANGUAGE sql STABLE;

-- Get processing statistics
CREATE OR REPLACE FUNCTION get_processing_stats(p_job_id UUID DEFAULT NULL)
RETURNS TABLE (
    total_files BIGINT,
    processed_files BIGINT,
    organized_files BIGINT,
    applied_files BIGINT,
    duplicate_groups BIGINT,
    version_chains BIGINT,
    pending_changes BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        (SELECT COUNT(*) FROM document_items WHERE (p_job_id IS NULL OR job_id = p_job_id) AND NOT is_deleted),
        (SELECT COUNT(*) FROM document_items WHERE (p_job_id IS NULL OR job_id = p_job_id) AND status IN ('processed', 'organized', 'applied')),
        (SELECT COUNT(*) FROM document_items WHERE (p_job_id IS NULL OR job_id = p_job_id) AND status IN ('organized', 'applied')),
        (SELECT COUNT(*) FROM document_items WHERE (p_job_id IS NULL OR job_id = p_job_id) AND status = 'applied'),
        (SELECT COUNT(*) FROM duplicate_groups),
        (SELECT COUNT(*) FROM version_chains),
        (SELECT COUNT(*) FROM document_items WHERE (p_job_id IS NULL OR job_id = p_job_id) AND (has_name_change OR has_path_change) AND status = 'organized');
END;
$$ LANGUAGE plpgsql STABLE;

-- Update tag usage counts
CREATE OR REPLACE FUNCTION update_tag_usage_counts()
RETURNS void AS $$
BEGIN
    UPDATE tag_taxonomy t
    SET usage_count = (
        SELECT COUNT(*)
        FROM document_items d
        WHERE t.tag_name = ANY(d.proposed_tags)
          AND d.is_deleted = FALSE
    );
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- VIEWS
-- =============================================================================

-- Files ready for processing
CREATE OR REPLACE VIEW v_files_to_process AS
SELECT id, file_id, current_name, current_path, current_extension, 
       file_size_bytes, mime_type, content_hash
FROM document_items
WHERE status = 'discovered' 
  AND is_deleted = FALSE
  AND current_extension = ANY(ARRAY[
      'pdf', 'docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt',
      'txt', 'md', 'csv', 'html', 'json', 'xml',
      'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'svg', 'webp',
      'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm',
      'mp3', 'wav', 'flac', 'aac', 'ogg', 'wma',
      'zip', 'rar', '7z', 'tar', 'gz',
      'exe', 'msi', 'dmg'
  ])
ORDER BY current_path;

-- Files ready for organization  
CREATE OR REPLACE VIEW v_files_to_organize AS
SELECT d.id, d.file_id, d.current_name, d.current_path, d.current_extension,
       d.content_summary, d.document_type, d.key_topics, d.source_modified_at
FROM document_items d
LEFT JOIN duplicate_members dm ON d.id = dm.document_id AND dm.action = 'shortcut'
LEFT JOIN version_chain_members vcm ON d.id = vcm.document_id AND vcm.status = 'superseded'
WHERE d.status = 'processed'
  AND d.is_deleted = FALSE
  AND dm.id IS NULL  -- Not marked as shortcut duplicate
  AND vcm.id IS NULL -- Not a superseded version
ORDER BY d.current_path;

-- Pending changes summary
CREATE OR REPLACE VIEW v_pending_changes AS
SELECT 
    id, current_name, proposed_name,
    current_path, proposed_path,
    proposed_tags,
    organization_reasoning,
    CASE 
        WHEN has_name_change AND has_path_change THEN 'rename_and_move'
        WHEN has_name_change THEN 'rename'
        WHEN has_path_change THEN 'move'
        ELSE 'no_change'
    END as change_type
FROM document_items
WHERE status = 'organized'
  AND (has_name_change OR has_path_change)
ORDER BY proposed_path, proposed_name;

-- Duplicate summary
CREATE OR REPLACE VIEW v_duplicate_summary AS
SELECT 
    dg.id as group_id,
    dg.content_hash,
    dg.file_count,
    pg_size_pretty(dg.total_size_bytes) as total_size,
    primary_doc.current_name as primary_name,
    primary_doc.current_path as primary_path,
    array_agg(dup_doc.current_path) FILTER (WHERE dm.action = 'shortcut') as shortcut_paths
FROM duplicate_groups dg
JOIN document_items primary_doc ON dg.primary_document_id = primary_doc.id
LEFT JOIN duplicate_members dm ON dg.id = dm.group_id
LEFT JOIN document_items dup_doc ON dm.document_id = dup_doc.id
GROUP BY dg.id, dg.content_hash, dg.file_count, dg.total_size_bytes,
         primary_doc.current_name, primary_doc.current_path;

-- Version chains summary
CREATE OR REPLACE VIEW v_version_chains_summary AS
SELECT 
    vc.id as chain_id,
    vc.chain_name,
    vc.base_path,
    vc.detection_method,
    vc.archive_strategy,
    current_doc.current_name as current_file,
    COUNT(vcm.id) as version_count,
    array_agg(vcm.version_label ORDER BY vcm.version_number) as versions
FROM version_chains vc
LEFT JOIN document_items current_doc ON vc.current_document_id = current_doc.id
LEFT JOIN version_chain_members vcm ON vc.id = vcm.chain_id
GROUP BY vc.id, vc.chain_name, vc.base_path, vc.detection_method, 
         vc.archive_strategy, current_doc.current_name;

-- Recent errors
CREATE OR REPLACE VIEW v_recent_errors AS
SELECT 
    pl.created_at,
    pl.action,
    pl.phase,
    pl.error_message,
    di.current_name,
    di.current_path
FROM processing_log pl
LEFT JOIN document_items di ON pl.document_id = di.id
WHERE pl.success = FALSE
ORDER BY pl.created_at DESC
LIMIT 100;

-- Directory summary
CREATE OR REPLACE VIEW v_directory_summary AS
SELECT 
    ds.path,
    ds.purpose,
    ds.expected_tags,
    COUNT(di.id) as planned_file_count,
    pg_size_pretty(SUM(di.file_size_bytes)) as planned_size
FROM directory_structure ds
LEFT JOIN document_items di ON di.proposed_path = ds.path AND di.status = 'organized'
WHERE ds.is_active = TRUE
GROUP BY ds.id, ds.path, ds.purpose, ds.expected_tags
ORDER BY ds.depth, ds.path;

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Update timestamps
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_version_chains_updated
    BEFORE UPDATE ON version_chains
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER tr_naming_schema_updated
    BEFORE UPDATE ON naming_schema
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER tr_system_config_updated
    BEFORE UPDATE ON system_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- GRANTS (adjust as needed for your user)
-- =============================================================================

-- Example: GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO doc_organizer;
-- Example: GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO doc_organizer;
-- Example: GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO doc_organizer;

-- =============================================================================
-- COMPLETION
-- =============================================================================

-- Log schema creation
DO $$
BEGIN
    RAISE NOTICE 'Document Organizer v2 schema created successfully';
    RAISE NOTICE 'Tables: processing_jobs, document_items, duplicate_groups, duplicate_members';
    RAISE NOTICE 'Tables: version_chains, version_chain_members';
    RAISE NOTICE 'Tables: naming_schema, tag_taxonomy, directory_structure';
    RAISE NOTICE 'Tables: shortcut_files, execution_log, processing_log, system_config';
END $$;
