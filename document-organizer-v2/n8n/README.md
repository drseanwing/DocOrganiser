# n8n Workflows for Document Organizer

This directory contains n8n workflow JSON files for integrating the Document Organizer system with cloud storage (OneDrive/SharePoint).

## Overview

The n8n workflows handle the cloud integration layer:

1. **workflow_download.json** - Downloads folders from OneDrive/SharePoint as ZIP
2. **workflow_trigger.json** - Triggers Docker container processing
3. **workflow_upload.json** - Uploads reorganized results back to cloud
4. **workflow_webhook.json** - Receives processing callbacks and routes events

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   OneDrive/     │────▶│   n8n Server    │────▶│ Docker Container│
│   SharePoint    │     │                 │     │ (Processing)    │
│                 │◀────│  Workflows:     │◀────│                 │
│                 │     │  1. Download    │     │  - Index        │
│   (Cloud)       │     │  2. Trigger     │     │  - Dedup        │
│                 │     │  3. Upload      │     │  - Version      │
└─────────────────┘     │  4. Webhook     │     │  - Organize     │
                        └─────────────────┘     └─────────────────┘
```

## Prerequisites

- n8n installed (self-hosted or cloud)
- PostgreSQL database (shared with Document Organizer)
- Microsoft Azure AD application with Graph API permissions
- Docker environment with Document Organizer running
- Network connectivity between n8n and Docker containers

## Installation

### 1. Deploy n8n

Choose one of the following deployment methods:

#### Option A: Docker Compose (recommended for integration)

```yaml
# Add to your docker-compose.yml
n8n:
  image: n8nio/n8n:latest
  container_name: doc_organizer_n8n
  restart: unless-stopped
  ports:
    - "5678:5678"
  environment:
    - N8N_BASIC_AUTH_ACTIVE=true
    - N8N_BASIC_AUTH_USER=${N8N_USER}
    - N8N_BASIC_AUTH_PASSWORD=${N8N_PASSWORD}
    - WEBHOOK_URL=${N8N_WEBHOOK_URL}
    - GENERIC_TIMEZONE=America/New_York
  volumes:
    - n8n_data:/home/node/.n8n
  networks:
    - doc_organizer_network
```

#### Option B: Standalone Docker

```bash
docker run -d \
  --name n8n \
  -p 5678:5678 \
  -e N8N_BASIC_AUTH_ACTIVE=true \
  -e N8N_BASIC_AUTH_USER=admin \
  -e N8N_BASIC_AUTH_PASSWORD=changeme \
  -v n8n_data:/home/node/.n8n \
  --network doc_organizer_network \
  n8nio/n8n
```

#### Option C: n8n Cloud

Use n8n cloud service at https://n8n.io - configure webhook URLs to point to your n8n cloud instance.

### 2. Import Workflows

1. Access n8n UI at http://localhost:5678
2. Login with your credentials
3. Go to **Workflows** → **Import from File**
4. Import each workflow JSON file:
   - `workflow_download.json`
   - `workflow_trigger.json`
   - `workflow_upload.json`
   - `workflow_webhook.json`

### 3. Configure Credentials

#### PostgreSQL Credential

1. Go to **Settings** → **Credentials** → **New**
2. Select **Postgres**
3. Configure:
   ```
   Host: postgres (or your database host)
   Port: 5432
   Database: document_organizer
   User: doc_organizer
   Password: <your password>
   SSL: false (or true if using SSL)
   ```
4. Name it: "Document Organizer DB"
5. Save

#### Microsoft OAuth (Optional - for built-in OAuth)

If using n8n's built-in Microsoft OAuth node:

1. Go to **Settings** → **Credentials** → **New**
2. Select **Microsoft OAuth2 API**
3. Configure:
   ```
   Client ID: <your Azure AD app client ID>
   Client Secret: <your Azure AD app client secret>
   Tenant ID: <your Azure AD tenant ID>
   ```
4. Click **Connect my account**
5. Complete OAuth flow

**Note:** The workflows use HTTP Request nodes with manual token management for more control. The OAuth credential is optional.

#### SMTP Credential (for notifications)

1. Go to **Settings** → **Credentials** → **New**
2. Select **SMTP**
3. Configure your SMTP settings
4. Name it: "SMTP"
5. Save

## Environment Variables

Configure these environment variables in n8n:

### Microsoft Graph API

```bash
# Azure AD Configuration
MS_TENANT_ID=your-tenant-id
MS_CLIENT_ID=your-client-id
MS_CLIENT_SECRET=your-client-secret

# Source Configuration
SOURCE_TYPE=onedrive          # or 'sharepoint'
SOURCE_PATH=/Documents/ToOrganize
SOURCE_SITE_ID=your-site-id   # Required for SharePoint

# Target Configuration (for upload)
TARGET_PATH=/Documents/Organized
UPLOAD_STRATEGY=extract       # or 'zip-only'
```

### Database

```bash
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=document_organizer
POSTGRES_USER=doc_organizer
POSTGRES_PASSWORD=changeme
```

### Processing

```bash
# Container connection
PROCESSOR_HOST=processor
PROCESSOR_PORT=8000
TRIGGER_METHOD=http          # or 'file'

# n8n webhooks
N8N_WEBHOOK_URL=http://n8n:5678
```

### Notifications

```bash
SEND_NOTIFICATION=true
NOTIFICATION_EMAIL=user@example.com
SMTP_FROM=noreply@example.com
```

### Optional Settings

```bash
# Auto-approve reviews (skip manual review)
AUTO_APPROVE=false

# Cleanup source files after upload
CLEANUP_SOURCE=false
```

## Azure AD App Setup

### Required Permissions

Your Azure AD application needs the following Microsoft Graph API permissions:

#### Application Permissions (Client Credentials Flow)

- `Files.ReadWrite.All` - Read and write files in all site collections
- `Sites.ReadWrite.All` - Read and write items in all site collections (for SharePoint)

### Setup Steps

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** → **App registrations**
3. Click **New registration**
4. Configure:
   - Name: "Document Organizer Integration"
   - Supported account types: Single tenant
   - Redirect URI: (leave blank for client credentials)
5. Click **Register**
6. Note the **Application (client) ID** and **Directory (tenant) ID**
7. Go to **API permissions**:
   - Click **Add a permission**
   - Select **Microsoft Graph**
   - Select **Application permissions**
   - Add `Files.ReadWrite.All`
   - Add `Sites.ReadWrite.All` (if using SharePoint)
   - Click **Grant admin consent**
8. Go to **Certificates & secrets**:
   - Click **New client secret**
   - Description: "n8n workflows"
   - Expires: Choose duration
   - Click **Add**
   - **IMPORTANT:** Copy the secret value immediately (you won't see it again)

### Find SharePoint Site ID

If using SharePoint, you need the Site ID:

```bash
# Get site ID
curl -X GET \
  "https://graph.microsoft.com/v1.0/sites/{your-domain}.sharepoint.com:/sites/{site-name}" \
  -H "Authorization: Bearer {access_token}"

# Response contains: "id": "site-id"
```

## Usage

### Workflow 1: Download from Cloud

**Purpose:** Download a folder from OneDrive/SharePoint as ZIP

**Trigger Methods:**

1. **Manual:** Click "Execute Workflow" in n8n UI
2. **Schedule:** Add Schedule Trigger node (e.g., daily at 2 AM)
3. **Webhook:** Call workflow via HTTP endpoint

**Process:**

1. Authenticates with Microsoft Graph API
2. Creates processing job in database
3. Lists all files recursively in the source folder
4. Downloads files in batches (respects rate limits)
5. Creates ZIP archive
6. Saves to `/data/input/source_{jobId}.zip`
7. Triggers processing workflow

**Expected Duration:** 2-10 minutes depending on folder size

### Workflow 2: Trigger Processing

**Purpose:** Start Docker container processing

**Trigger:** Webhook from Download workflow

**Process:**

1. Validates webhook payload
2. Verifies ZIP file exists
3. Updates job status to "processing"
4. Triggers Docker container via HTTP or file-based trigger
5. Returns immediately (processing happens asynchronously)

**Trigger Methods:**

- **HTTP:** Calls processor container HTTP endpoint (requires container to expose API)
- **File:** Creates `.ready` file that container watches

### Workflow 3: Upload Results

**Purpose:** Upload reorganized files back to cloud

**Trigger:** Webhook from processing container on completion

**Process:**

1. Gets job details from database
2. Authenticates with Microsoft Graph API
3. Reads output ZIP
4. **Strategy A (extract):** Extracts files and uploads folder structure
5. **Strategy B (zip-only):** Uploads ZIP file as-is
6. Updates job status to "completed"
7. Cleans up temporary files
8. Sends notification (if enabled)

**Upload Strategies:**

- `extract`: Recreates folder structure in cloud (preserves organization)
- `zip-only`: Uploads single ZIP file (faster, requires manual extraction)

### Workflow 4: Webhook Receiver

**Purpose:** Receive and route processing callbacks

**Endpoints:**

- `/webhook/processing-callback` - All events

**Event Types:**

1. **processing_started** - Processing has begun
2. **phase_complete** - A phase (index, dedup, version, organize) completed
3. **review_required** - Manual review needed
4. **processing_complete** - Processing finished, ready for upload
5. **processing_failed** - An error occurred

**Actions:**

- Updates database with current status
- Logs events for tracking
- Sends notifications when configured
- Auto-approves if enabled
- Triggers upload workflow on completion

## Monitoring

### Check Workflow Execution

1. Go to **Executions** in n8n UI
2. View execution history
3. Click on execution to see detailed logs
4. Check for errors or warnings

### Database Monitoring

Query job status:

```sql
-- Get all jobs
SELECT id, status, current_phase, created_at, completed_at 
FROM processing_jobs 
ORDER BY created_at DESC;

-- Get job details
SELECT * FROM processing_jobs WHERE id = 'job-id';

-- Get processing events
SELECT * FROM processing_events WHERE job_id = 'job-id' ORDER BY created_at;
```

### Container Logs

```bash
# n8n logs
docker logs -f doc_organizer_n8n

# Processor logs
docker logs -f doc_organizer_processor
```

## Troubleshooting

### Common Issues

#### 1. "Failed to get OAuth token"

**Cause:** Invalid Azure AD credentials or permissions

**Solution:**
- Verify MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET
- Check Azure AD app permissions are granted
- Ensure client secret hasn't expired

#### 2. "ZIP file not found"

**Cause:** Download workflow didn't complete or file was deleted

**Solution:**
- Check download workflow execution logs
- Verify `/data/input` directory exists and is writable
- Check disk space

#### 3. "Rate limit exceeded (429)"

**Cause:** Too many API requests to Microsoft Graph

**Solution:**
- Workflows have built-in retry logic with exponential backoff
- Wait for retry-after header duration
- Reduce batch sizes if needed

#### 4. "Database connection failed"

**Cause:** PostgreSQL not accessible or wrong credentials

**Solution:**
- Verify database is running: `docker ps | grep postgres`
- Test connection: `psql -h postgres -U doc_organizer -d document_organizer`
- Check network connectivity between n8n and database

#### 5. "Webhook not receiving callbacks"

**Cause:** Container can't reach n8n or wrong URL

**Solution:**
- Verify N8N_WEBHOOK_URL is correct
- Test webhook: `curl -X POST http://n8n:5678/webhook/processing-callback -d '{"event":"test"}'`
- Check network connectivity
- Ensure webhook is activated in n8n

#### 6. "Upload failed - unauthorized"

**Cause:** Token expired or insufficient permissions

**Solution:**
- Token refresh is automatic, wait for retry
- Verify upload permissions in Azure AD app
- Check target path exists and is writable

### Enable Debug Logging

In n8n environment variables:

```bash
N8N_LOG_LEVEL=debug
N8N_LOG_OUTPUT=console
```

## Testing

### Test with Small Folder

1. Create a small test folder (5-10 files) in OneDrive/SharePoint
2. Update SOURCE_PATH to point to test folder
3. Execute Download workflow manually
4. Monitor execution in n8n UI
5. Verify ZIP created in `/data/input/`
6. Check database for job record

### Test End-to-End

```bash
# 1. Start all services
docker-compose up -d

# 2. Execute download workflow (via n8n UI)

# 3. Monitor processing
docker logs -f doc_organizer_processor

# 4. Check job status
psql -h localhost -U doc_organizer -d document_organizer -c \
  "SELECT id, status, current_phase FROM processing_jobs ORDER BY created_at DESC LIMIT 1;"

# 5. Verify upload (check OneDrive/SharePoint)
```

### Test Individual Workflows

Each workflow can be tested independently:

```bash
# Test download
curl -X POST http://localhost:5678/webhook/trigger-download

# Test trigger (requires existing ZIP)
curl -X POST http://localhost:5678/webhook/trigger-processing \
  -H "Content-Type: application/json" \
  -d '{"jobId":"test-job-id","zipPath":"/data/input/test.zip"}'

# Test webhook receiver
curl -X POST http://localhost:5678/webhook/processing-callback \
  -H "Content-Type: application/json" \
  -d '{"event":"processing_started","job_id":"test-job-id"}'

# Test upload (requires completed job)
curl -X POST http://localhost:5678/webhook/processing-complete \
  -H "Content-Type: application/json" \
  -d '{"job_id":"test-job-id","output_path":"/data/output/test.zip"}'
```

## Security Considerations

### Secrets Management

- Never commit credentials to version control
- Use n8n's credential management system
- Rotate secrets regularly (especially client secrets)
- Use environment variables for sensitive data

### Network Security

- Run n8n behind reverse proxy with HTTPS
- Use authentication (basic auth or OAuth)
- Restrict network access to trusted sources
- Use firewall rules to limit container access

### Webhook Security

- Use webhook authentication if exposed to internet
- Validate webhook payloads
- Rate limit webhook endpoints
- Log all webhook calls for auditing

### Data Protection

- Temporary files are cleaned up after processing
- ZIP files contain sensitive data - secure the `/data` volume
- Database contains metadata - secure PostgreSQL
- Use encryption at rest for volumes

## Performance Optimization

### Batch Sizes

Adjust batch sizes in workflows based on:

- Network speed
- File sizes
- API rate limits

Current defaults:
- Download: 10 files per batch
- Upload: 5 files per batch

### Parallel Processing

Enable parallel execution in n8n settings for better performance with large folders.

### Caching

Consider caching OAuth tokens to reduce authentication requests:

- Tokens are valid for 60-90 minutes
- Store in n8n static data or database
- Refresh before expiry

## Backup and Recovery

### Backup n8n Data

```bash
# Backup n8n database and workflows
docker run --rm \
  -v n8n_data:/data \
  -v $(pwd)/backup:/backup \
  alpine tar czf /backup/n8n-backup-$(date +%Y%m%d).tar.gz /data
```

### Restore n8n Data

```bash
# Restore from backup
docker run --rm \
  -v n8n_data:/data \
  -v $(pwd)/backup:/backup \
  alpine tar xzf /backup/n8n-backup-YYYYMMDD.tar.gz -C /
```

### Export Workflows

Regularly export workflows as JSON files for version control:

1. Go to each workflow in n8n UI
2. Click **...** → **Download**
3. Save JSON file
4. Commit to version control

## Support

### Resources

- [n8n Documentation](https://docs.n8n.io/)
- [Microsoft Graph API Docs](https://docs.microsoft.com/en-us/graph/)
- [Document Organizer README](../README.md)

### Reporting Issues

When reporting issues, include:

1. Workflow execution logs from n8n
2. Container logs if applicable
3. Database query results showing job status
4. Environment configuration (sanitized)
5. Steps to reproduce

## License

These workflows are part of the Document Organizer project. See main README for license information.

## Changelog

### Version 2.0.0 (2024-01-22)

- Initial release of n8n workflows
- Support for OneDrive and SharePoint
- Multiple upload strategies
- Comprehensive error handling
- Event-driven architecture with webhooks
- Auto-approval option for reviews
- Email notifications
