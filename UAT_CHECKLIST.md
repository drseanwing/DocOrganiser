# DocOrganiser - UAT Testing Checklist

## Overview

This checklist ensures all components of DocOrganiser are tested and ready for User Acceptance Testing (UAT).

**Test Environment:**
- Platform: Docker containers
- Database: PostgreSQL 15+
- Storage: SharePoint/OneDrive
- LLM: Ollama (local) + Claude (cloud)

---

## Pre-UAT Setup

### 1. Environment Preparation

- [ ] **Docker Environment**
  - [ ] Docker and Docker Compose installed
  - [ ] Sufficient disk space (minimum 20GB)
  - [ ] Network connectivity configured
  - [ ] Ports available: 5432 (PostgreSQL), 8000 (API), 11434 (Ollama)

- [ ] **Azure AD Application**
  - [ ] Application registered in Azure Portal
  - [ ] Client ID and Client Secret generated
  - [ ] Required permissions granted:
    - [ ] `Files.ReadWrite.All` (Application)
    - [ ] `Sites.ReadWrite.All` (Application)
  - [ ] Admin consent granted
  - [ ] Credentials documented securely

- [ ] **Anthropic Claude API**
  - [ ] API key obtained
  - [ ] API key tested and active
  - [ ] Billing configured (if applicable)

- [ ] **SharePoint Site**
  - [ ] SharePoint site created
  - [ ] Test folders created:
    - [ ] `/Documents/ToOrganize` (source)
    - [ ] `/Documents/Organized` (output)
  - [ ] Permissions verified

### 2. Initial Deployment

- [ ] **Clone Repository**
  ```bash
  git clone https://github.com/drseanwing/DocOrganiser.git
  cd DocOrganiser/document-organizer-v2
  ```

- [ ] **Configure Environment**
  - [ ] Copy `.env.example` to `.env`
  - [ ] Set database credentials
  - [ ] Set API keys (optional for first boot)

- [ ] **Start Services**
  ```bash
  docker-compose up -d
  ```

- [ ] **Verify Services Running**
  - [ ] PostgreSQL: `docker ps | grep postgres`
  - [ ] Ollama: `docker ps | grep ollama`
  - [ ] Processor: `docker ps | grep processor`

- [ ] **Database Initialization**
  - [ ] Schema created automatically
  - [ ] Tables exist: `processing_jobs`, `document_items`, etc.
  - [ ] `api_configuration` table created

---

## Component Testing

### 1. Admin Interface Testing

#### Access and UI

- [ ] **Access Interface**
  - [ ] Navigate to `http://localhost:8000/admin`
  - [ ] Page loads without errors
  - [ ] All sections visible
  - [ ] No console errors in browser

#### Configuration Management

- [ ] **Microsoft Graph API Configuration**
  - [ ] Enter Tenant ID
  - [ ] Enter Client ID
  - [ ] Enter Client Secret
  - [ ] Save configuration
  - [ ] Verify success message
  - [ ] Reload page - verify values persist (secret masked)

- [ ] **Ollama Configuration**
  - [ ] Update Ollama Base URL
  - [ ] Select model (e.g., `mistral`)
  - [ ] Save configuration
  - [ ] Verify success message

- [ ] **Claude API Configuration**
  - [ ] Enter Claude API key
  - [ ] Select model
  - [ ] Save configuration
  - [ ] Verify success message

- [ ] **Processing Settings**
  - [ ] Set source folder path
  - [ ] Set output folder path
  - [ ] Set notification email
  - [ ] Toggle auto-approve (keep off for UAT)
  - [ ] Save configuration

#### Connectivity Testing

- [ ] **Test All Services**
  - [ ] Click "Test Connections" button
  - [ ] Database: ✓ Success
  - [ ] Ollama: ✓ Success
  - [ ] Claude API: ✓ Success (if configured)
  - [ ] Microsoft Graph: ✓ Success (if configured)
  - [ ] Response times reasonable (<2 seconds each)

#### Error Handling

- [ ] **Invalid Credentials**
  - [ ] Enter invalid Tenant ID
  - [ ] Test connectivity
  - [ ] Verify error message displayed
  - [ ] Restore valid credentials

- [ ] **Masked Secrets**
  - [ ] Leave secret field blank
  - [ ] Save configuration
  - [ ] Verify existing secret NOT overwritten
  - [ ] Test connectivity still works

### 2. PowerAutomate Flows Testing

#### Flow Import

- [ ] **Import Flows to PowerAutomate**
  - [ ] Schema initialization flow imported
  - [ ] Auth token flow imported
  - [ ] API with bearer token flow imported
  - [ ] All connections configured

#### Schema Initialization

- [ ] **Run Schema Init Flow**
  - [ ] Execute with test parameters
  - [ ] Verify SharePoint lists created:
    - [ ] `DocOrganiser_Configuration`
    - [ ] `DocOrganiser_TokenCache`
    - [ ] `DocOrganiser_Jobs`
  - [ ] Verify email notification received
  - [ ] Check list permissions are restricted

#### Token Retrieval

- [ ] **Run Auth Token Flow**
  - [ ] Execute flow manually
  - [ ] Verify token received in response
  - [ ] Check token cached in SharePoint
  - [ ] Verify token expiration time set
  - [ ] Test with invalid credentials (should fail gracefully)

#### Bearer Token API Call

- [ ] **Run API Call Flow**
  - [ ] Test GET request to Graph API
  - [ ] Verify cached token used
  - [ ] Verify response returned
  - [ ] Test with expired token (should auto-refresh)
  - [ ] Test 401 error handling

### 3. Backend API Testing

#### Health Check

- [ ] **API Health**
  - [ ] `GET /health` returns 200
  - [ ] Response includes version
  - [ ] Database connection verified

#### Job Management

- [ ] **Create Test Job**
  - [ ] Create small test ZIP file (5-10 files)
  - [ ] `POST /webhook/job` with ZIP path
  - [ ] Verify job_id returned
  - [ ] Verify job created in database

- [ ] **Check Job Status**
  - [ ] `GET /jobs/{job_id}/status`
  - [ ] Verify status updates as processing progresses
  - [ ] Verify current_phase changes

- [ ] **Job Report**
  - [ ] `GET /jobs/{job_id}/report`
  - [ ] Verify statistics accurate
  - [ ] Verify report HTML path (if review_required)

#### Admin API

- [ ] **Configuration CRUD**
  - [ ] `GET /admin/config` - returns masked secrets
  - [ ] `POST /admin/config` - updates configuration
  - [ ] Partial updates work (only provided fields updated)
  - [ ] Secrets not overwritten when blank

- [ ] **Connectivity Tests**
  - [ ] `POST /admin/test-connectivity`
  - [ ] All services tested
  - [ ] Results accurate
  - [ ] Response times included

### 4. Processing Pipeline Testing

#### Index Agent

- [ ] **File Discovery**
  - [ ] Create test folder with various file types
  - [ ] Run index agent
  - [ ] Verify all files discovered
  - [ ] Verify file metadata extracted:
    - [ ] File size
    - [ ] MIME type
    - [ ] Created/modified dates
    - [ ] Content hash (SHA256)

- [ ] **Content Summarization**
  - [ ] Verify Ollama summarizes documents
  - [ ] Verify summaries stored in database
  - [ ] Check document_type detection
  - [ ] Check key_topics extraction

#### Dedup Agent

- [ ] **Duplicate Detection**
  - [ ] Create duplicate files (identical content)
  - [ ] Run dedup agent
  - [ ] Verify duplicate groups created
  - [ ] Verify primary file selected
  - [ ] Verify duplicate actions assigned (shortcut/keep-both)

- [ ] **LLM Decision Making**
  - [ ] Verify LLM used for ambiguous cases
  - [ ] Verify reasoning stored
  - [ ] Verify fallback logic when LLM unavailable

#### Version Agent

- [ ] **Version Detection**
  - [ ] Create files with version markers (`_v1`, `_v2`, `_rev1`)
  - [ ] Run version agent
  - [ ] Verify version chains created
  - [ ] Verify version numbers assigned
  - [ ] Verify current version identified

- [ ] **Version Sorting**
  - [ ] Test explicit version numbers
  - [ ] Test date-based versioning
  - [ ] Test status markers (draft/final)
  - [ ] Verify correct version order

#### Organize Agent

- [ ] **Organization Planning**
  - [ ] Run organize agent
  - [ ] Verify Claude API called
  - [ ] Verify naming schemas created
  - [ ] Verify tag taxonomy generated
  - [ ] Verify directory structure proposed
  - [ ] Verify file assignments made

- [ ] **Quality Checks**
  - [ ] Verify proposed names are descriptive
  - [ ] Verify no invalid characters in names
  - [ ] Verify tags are relevant
  - [ ] Verify directory structure is logical

#### Execution Engine

- [ ] **Dry Run Mode**
  - [ ] Enable dry_run in config
  - [ ] Run execution
  - [ ] Verify no files actually moved/renamed
  - [ ] Verify execution log created
  - [ ] Verify manifest generated

- [ ] **Real Execution**
  - [ ] Disable dry_run
  - [ ] Run execution with small test set
  - [ ] Verify directories created
  - [ ] Verify files moved to correct locations
  - [ ] Verify files renamed correctly
  - [ ] Verify shortcuts created for duplicates
  - [ ] Verify version archives created
  - [ ] Verify manifests generated

### 5. Microsoft Graph Integration Testing

#### Authentication

- [ ] **Token Acquisition**
  - [ ] GraphService obtains token
  - [ ] Token cached with expiration
  - [ ] Token refresh works when expired
  - [ ] 401 errors trigger token refresh

#### File Operations

- [ ] **List Files**
  - [ ] List files in OneDrive root
  - [ ] List files in specific folder
  - [ ] Recursive listing works
  - [ ] Pagination handled correctly

- [ ] **Download Files**
  - [ ] Download small file (<1MB)
  - [ ] Download medium file (1-4MB)
  - [ ] Download large file (>4MB)
  - [ ] Verify content integrity (hash matches)

- [ ] **Upload Files**
  - [ ] Upload small file (<4MB) - simple upload
  - [ ] Upload large file (>4MB) - chunked upload
  - [ ] Verify file appears in SharePoint
  - [ ] Verify content integrity

- [ ] **Folder Management**
  - [ ] Create folder in OneDrive
  - [ ] Create nested folders
  - [ ] Check folder exists before creating

### 6. n8n Workflows Testing (if deployed)

- [ ] **Download Workflow**
  - [ ] Manually trigger workflow
  - [ ] Verify files downloaded from SharePoint
  - [ ] Verify ZIP created
  - [ ] Verify job created in database

- [ ] **Trigger Workflow**
  - [ ] Workflow called by download workflow
  - [ ] ZIP file verified
  - [ ] Processing started

- [ ] **Upload Workflow**
  - [ ] Triggered on processing completion
  - [ ] Files uploaded to SharePoint
  - [ ] Folder structure recreated
  - [ ] Notification sent

- [ ] **Webhook Workflow**
  - [ ] Receives processing callbacks
  - [ ] Routes events correctly
  - [ ] Updates database status
  - [ ] Sends notifications

---

## End-to-End Testing

### Scenario 1: Small File Set (10 files)

- [ ] **Setup**
  - [ ] Create folder with 10 diverse files
  - [ ] Include 2 duplicates
  - [ ] Include 2 versions (e.g., report_v1.docx, report_v2.docx)
  - [ ] Upload to SharePoint test folder

- [ ] **Execution**
  - [ ] Trigger download workflow (or create ZIP manually)
  - [ ] Wait for processing to complete
  - [ ] Review organization plan (if review_required)
  - [ ] Approve execution
  - [ ] Wait for upload to complete

- [ ] **Verification**
  - [ ] Check output folder in SharePoint
  - [ ] Verify files organized correctly
  - [ ] Verify duplicates handled (shortcuts created)
  - [ ] Verify versions archived
  - [ ] Verify all 10 files accounted for
  - [ ] Check manifests and logs

### Scenario 2: Medium File Set (50 files)

- [ ] **Setup**
  - [ ] Create folder with 50 files
  - [ ] Mix of file types (PDF, DOCX, XLSX, PPTX)
  - [ ] Include duplicates and versions
  - [ ] Include nested folders

- [ ] **Execution**
  - [ ] Process as in Scenario 1
  - [ ] Monitor performance
  - [ ] Check progress updates

- [ ] **Verification**
  - [ ] Verify all files processed
  - [ ] Check processing time (should be < 10 minutes)
  - [ ] Verify no errors in logs
  - [ ] Verify organization quality

### Scenario 3: Large File Set (100+ files)

- [ ] **Setup**
  - [ ] Create folder with 100+ files
  - [ ] Include large files (>10MB)
  - [ ] Complex folder structure

- [ ] **Execution**
  - [ ] Process with batch_size=50
  - [ ] Monitor system resources
  - [ ] Check for memory leaks

- [ ] **Verification**
  - [ ] All files processed successfully
  - [ ] Performance acceptable
  - [ ] No crashes or timeouts
  - [ ] Large files uploaded correctly

### Scenario 4: Error Handling

- [ ] **Invalid File Types**
  - [ ] Include unsupported file type
  - [ ] Verify skipped gracefully
  - [ ] Verify logged as skipped

- [ ] **Corrupted Files**
  - [ ] Include corrupted PDF
  - [ ] Verify error handling
  - [ ] Verify doesn't block other files

- [ ] **Network Interruption**
  - [ ] Simulate network failure during upload
  - [ ] Verify retry logic
  - [ ] Verify eventual success

- [ ] **Service Unavailable**
  - [ ] Stop Ollama service mid-processing
  - [ ] Verify fallback logic
  - [ ] Verify continues with Claude only

---

## Performance Testing

### Metrics to Collect

- [ ] **Processing Speed**
  - [ ] Files per minute
  - [ ] Time per processing phase
  - [ ] Total pipeline time

- [ ] **Resource Usage**
  - [ ] CPU utilization
  - [ ] Memory usage
  - [ ] Disk I/O
  - [ ] Network bandwidth

- [ ] **API Response Times**
  - [ ] Health check: < 100ms
  - [ ] Config retrieval: < 200ms
  - [ ] Connectivity tests: < 3s total
  - [ ] Job status: < 200ms

### Performance Targets

- [ ] **Index Agent**: 50+ files/minute
- [ ] **Dedup Agent**: 100+ files/minute
- [ ] **Version Agent**: 100+ files/minute
- [ ] **Organize Agent**: Claude API call < 30s
- [ ] **Execution**: 50+ operations/minute
- [ ] **Graph API**: 
  - [ ] Token acquisition < 2s
  - [ ] File download < 5s per file
  - [ ] File upload < 10s per file

---

## Security Testing

### Authentication

- [ ] **API Endpoints**
  - [ ] Admin endpoints require authentication (if configured)
  - [ ] Unauthorized access blocked
  - [ ] CORS configured correctly

### Secrets Management

- [ ] **Storage**
  - [ ] Secrets not visible in logs
  - [ ] Secrets masked in API responses
  - [ ] Secrets encrypted in database (if pgcrypto enabled)

- [ ] **Transmission**
  - [ ] HTTPS used in production
  - [ ] No secrets in URL parameters
  - [ ] No secrets in error messages

### Access Control

- [ ] **SharePoint Lists**
  - [ ] Configuration list restricted to admins
  - [ ] Token cache not publicly accessible
  - [ ] Job tracking visible to authorized users

### Vulnerability Scanning

- [ ] **Dependencies**
  - [ ] Run `pip audit` on requirements.txt
  - [ ] No critical vulnerabilities
  - [ ] All dependencies up to date

- [ ] **Docker Images**
  - [ ] Base images are official and up to date
  - [ ] No vulnerable packages in containers

---

## Documentation Review

- [ ] **README Files**
  - [ ] Main README.md accurate
  - [ ] Admin README.md comprehensive
  - [ ] PowerAutomate README.md complete
  - [ ] n8n README.md up to date

- [ ] **API Documentation**
  - [ ] OpenAPI docs at `/docs` work
  - [ ] All endpoints documented
  - [ ] Example requests/responses included

- [ ] **Deployment Guide**
  - [ ] Step-by-step instructions
  - [ ] Prerequisites listed
  - [ ] Troubleshooting section

- [ ] **UAT Checklist**
  - [ ] This checklist is complete
  - [ ] All test scenarios covered
  - [ ] Acceptance criteria clear

---

## UAT Sign-Off

### Pre-Production Checklist

- [ ] All component tests passed
- [ ] All end-to-end scenarios passed
- [ ] Performance targets met
- [ ] Security review completed
- [ ] Documentation reviewed and approved
- [ ] No critical or high-severity bugs
- [ ] Known issues documented

### Stakeholder Approval

- [ ] **Technical Lead**: _________________ Date: _______
- [ ] **Product Owner**: _________________ Date: _______
- [ ] **Security Lead**: _________________ Date: _______
- [ ] **UAT Lead**: _________________ Date: _______

### Production Readiness

- [ ] **Environment Setup**
  - [ ] Production environment provisioned
  - [ ] SSL certificates configured
  - [ ] Backup systems in place
  - [ ] Monitoring configured
  - [ ] Alert rules set up

- [ ] **Data Migration**
  - [ ] Test data archived
  - [ ] Production credentials configured
  - [ ] Initial configuration loaded

- [ ] **Rollback Plan**
  - [ ] Previous version tagged
  - [ ] Rollback procedure documented
  - [ ] Rollback tested

- [ ] **Launch Plan**
  - [ ] Deployment window scheduled
  - [ ] Communication plan ready
  - [ ] Support team briefed
  - [ ] Go-live checklist prepared

---

## Post-UAT Actions

### Issues Identified

| Issue ID | Description | Severity | Status | Resolution |
|----------|-------------|----------|--------|------------|
| | | | | |

### Recommendations

- [ ] Document all findings
- [ ] Prioritize bug fixes
- [ ] Schedule follow-up testing
- [ ] Update documentation based on feedback

### Next Steps

- [ ] Address critical issues
- [ ] Retest affected components
- [ ] Final sign-off meeting
- [ ] Production deployment

---

## Notes

Use this section for additional observations, questions, or concerns during UAT:

```
(Add notes here)
```

---

## Test Evidence

Attach or reference:
- [ ] Screenshots of successful tests
- [ ] Log files
- [ ] Performance metrics
- [ ] Test data samples
- [ ] Error reports

---

**Version**: 1.0.0  
**Date**: 2026-01-26  
**UAT Coordinator**: __________________  
**Test Environment**: __________________
