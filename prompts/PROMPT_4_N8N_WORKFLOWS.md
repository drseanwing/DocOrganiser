# PROMPT 4: n8n Workflows for Cloud Integration

## Context

You are implementing **n8n workflows** for a Document Organizer system. These workflows handle the cloud integration layer: downloading folders as ZIP from OneDrive/SharePoint, triggering the Docker container processing, and uploading the reorganized ZIP back to the cloud.

## System Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   OneDrive/     │────▶│   n8n Server    │────▶│ Docker Container│
│   SharePoint    │     │                 │     │ (Processing)    │
│                 │◀────│  Workflows:     │◀────│                 │
│                 │     │  1. Download    │     │  - Index        │
│   (Cloud)       │     │  2. Trigger     │     │  - Dedup        │
│                 │     │  3. Upload      │     │  - Version      │
└─────────────────┘     │  4. Webhook     │     │  - Organize     │
                        └─────────────────┘     │  - Execute      │
                                                └─────────────────┘
```

## Your Task

Create four n8n workflow JSON files:

1. **workflow_download.json** - Download folder as ZIP from OneDrive/SharePoint
2. **workflow_trigger.json** - Trigger Docker container processing
3. **workflow_upload.json** - Upload result ZIP back to cloud
4. **workflow_webhook.json** - Receive completion callbacks

## Microsoft Graph API Reference

### Authentication (Client Credentials Flow)
```
POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
Content-Type: application/x-www-form-urlencoded

client_id={client_id}
&scope=https://graph.microsoft.com/.default
&client_secret={client_secret}
&grant_type=client_credentials
```

### Download Folder as ZIP (OneDrive)
```
# Method 1: Download each file individually (more control)
GET https://graph.microsoft.com/v1.0/me/drive/root:/{path}:/children
GET https://graph.microsoft.com/v1.0/me/drive/items/{item-id}/content

# Method 2: Use delta + batch for efficiency
GET https://graph.microsoft.com/v1.0/me/drive/root:/{path}:/delta
```

### Download Folder (SharePoint)
```
GET https://graph.microsoft.com/v1.0/sites/{site-id}/drive/root:/{path}:/children
GET https://graph.microsoft.com/v1.0/sites/{site-id}/drive/items/{item-id}/content
```

### Upload File
```
# Small files (<4MB)
PUT https://graph.microsoft.com/v1.0/me/drive/root:/{path}/{filename}:/content
Content-Type: application/octet-stream
[file contents]

# Large files (>4MB) - Upload Session
POST https://graph.microsoft.com/v1.0/me/drive/root:/{path}/{filename}:/createUploadSession
{
  "item": { "@microsoft.graph.conflictBehavior": "rename" }
}
# Then PUT chunks to the uploadUrl
```

### Create Folder
```
POST https://graph.microsoft.com/v1.0/me/drive/root:/{parent-path}:/children
{
  "name": "New Folder",
  "folder": {},
  "@microsoft.graph.conflictBehavior": "rename"
}
```

## Workflow 1: Download Folder as ZIP

### Purpose
Download an entire folder from OneDrive/SharePoint, create a ZIP locally, and save to Docker volume.

### Flow
```
Manual Trigger / Schedule
    │
    ▼
Get OAuth Token
    │
    ▼
Create Processing Job (DB)
    │
    ▼
List Folder Contents (Recursive)
    │
    ▼
Download Each File
    │
    ▼
Create ZIP Archive
    │
    ▼
Save to /data/input/
    │
    ▼
Return Job ID
```

### Required Nodes

1. **Manual Trigger** or **Schedule Trigger**
   - Allow manual runs and scheduled processing

2. **HTTP Request - Get Token**
   ```json
   {
     "method": "POST",
     "url": "https://login.microsoftonline.com/{{ $env.MS_TENANT_ID }}/oauth2/v2.0/token",
     "body": {
       "client_id": "{{ $env.MS_CLIENT_ID }}",
       "scope": "https://graph.microsoft.com/.default",
       "client_secret": "{{ $env.MS_CLIENT_SECRET }}",
       "grant_type": "client_credentials"
     }
   }
   ```

3. **Postgres - Create Job**
   ```sql
   INSERT INTO processing_jobs (source_type, source_path, status, current_phase)
   VALUES ('onedrive', :path, 'downloading', 'downloading')
   RETURNING id;
   ```

4. **HTTP Request - List Folder**
   - Recursive listing with pagination (@odata.nextLink)
   - Handle both OneDrive and SharePoint paths

5. **Code Node - Build File List**
   ```javascript
   // Flatten recursive listing into array of files with paths
   const files = [];
   // ... recursion logic
   return files.map(f => ({
     id: f.id,
     name: f.name,
     path: f.parentReference.path,
     size: f.size,
     downloadUrl: f['@microsoft.graph.downloadUrl']
   }));
   ```

6. **Loop - Download Files**
   - Batch downloads (respect rate limits)
   - Save to temporary directory
   - Track progress

7. **Code Node - Create ZIP**
   ```javascript
   const AdmZip = require('adm-zip');
   const zip = new AdmZip();
   // Add all downloaded files maintaining structure
   zip.writeZip('/data/input/source_' + jobId + '.zip');
   ```

8. **Postgres - Update Job**
   ```sql
   UPDATE processing_jobs 
   SET source_zip_path = :zipPath, 
       source_file_count = :count,
       status = 'downloaded'
   WHERE id = :jobId;
   ```

### Environment Variables
```
MS_TENANT_ID - Azure AD tenant ID
MS_CLIENT_ID - App registration client ID
MS_CLIENT_SECRET - App registration secret
SOURCE_TYPE - 'onedrive' or 'sharepoint'
SOURCE_PATH - Path to folder (e.g., '/Documents/ToOrganize')
SOURCE_SITE_ID - SharePoint site ID (if SharePoint)
POSTGRES_* - Database connection
```

### Error Handling
- Retry failed downloads (3 attempts with backoff)
- Log partial failures
- Clean up temp files on error
- Update job status to 'failed' with error message

---

## Workflow 2: Trigger Processing

### Purpose
Trigger the Docker container to start processing a downloaded ZIP.

### Options

**Option A: Docker API (if n8n has Docker access)**
```
POST /containers/{container_id}/exec
{
  "Cmd": ["python", "-m", "src.main", "--zip", "/data/input/source.zip"]
}
```

**Option B: File-based trigger (container watches /data/input)**
- Just ensure file is in place
- Container's watch mode picks it up

**Option C: HTTP trigger to container**
```
POST http://processor:8000/process
{
  "zip_path": "/data/input/source_abc123.zip",
  "job_id": "abc123"
}
```

### Flow
```
Webhook (from Download workflow)
    │
    ▼
Verify ZIP exists
    │
    ▼
Trigger Container Processing
    │
    ▼
Update Job Status
    │
    ▼
(Container processes asynchronously)
```

### Required Nodes

1. **Webhook Trigger** (from Download workflow) or **Schedule Check**

2. **Code Node - Find Pending ZIPs**
   ```javascript
   // List files in /data/input/ matching *.zip (not *.processed)
   const fs = require('fs');
   const files = fs.readdirSync('/data/input')
     .filter(f => f.endsWith('.zip') && !f.includes('.processed'));
   return files.map(f => ({ filename: f }));
   ```

3. **HTTP Request - Trigger Processing** (if container has HTTP endpoint)
   ```json
   {
     "method": "POST",
     "url": "http://processor:8000/process",
     "body": {
       "zip_path": "/data/input/{{ $json.filename }}",
       "callback_url": "http://n8n:5678/webhook/processing-complete"
     }
   }
   ```

4. **Postgres - Update Job**
   ```sql
   UPDATE processing_jobs 
   SET status = 'processing', started_at = NOW()
   WHERE source_zip_path LIKE '%' || :filename;
   ```

---

## Workflow 3: Upload Results

### Purpose
Upload the reorganized ZIP back to OneDrive/SharePoint, optionally extracting to folder structure.

### Flow
```
Webhook (processing complete)
    │
    ▼
Get OAuth Token
    │
    ▼
Read Output ZIP
    │
    ▼
Option A: Upload ZIP as-is
    │
    ▼
Option B: Extract and Upload Folder Structure
    │
    ▼
Update Job Status = 'completed'
    │
    ▼
Cleanup temporary files
    │
    ▼
Send notification (optional)
```

### Required Nodes

1. **Webhook Trigger** - Receive completion callback

2. **Postgres - Get Job Details**
   ```sql
   SELECT * FROM processing_jobs WHERE id = :jobId;
   ```

3. **HTTP Request - Get Token** (reuse from Workflow 1)

4. **Code Node - Read ZIP / Extract**
   ```javascript
   const AdmZip = require('adm-zip');
   const zip = new AdmZip('/data/output/organized_abc123.zip');
   const entries = zip.getEntries();
   return entries.map(e => ({
     path: e.entryName,
     isDirectory: e.isDirectory,
     content: e.isDirectory ? null : e.getData()
   }));
   ```

5. **Loop - Create Folders**
   ```
   POST https://graph.microsoft.com/v1.0/me/drive/root:/{path}:/children
   { "name": "{folderName}", "folder": {} }
   ```

6. **Loop - Upload Files**
   - Small files: Direct PUT
   - Large files: Upload session
   - Batch for efficiency

7. **Postgres - Complete Job**
   ```sql
   UPDATE processing_jobs 
   SET status = 'completed', 
       completed_at = NOW(),
       output_uploaded = TRUE
   WHERE id = :jobId;
   ```

8. **IF - Send Notification**
   - Email via SMTP node
   - Slack/Teams message
   - Webhook to external system

### Upload Strategies

**Strategy A: Replace Original Folder**
1. Rename original folder to `{name}_backup_{date}`
2. Upload new structure to original location
3. Delete backup after confirmation

**Strategy B: Upload to New Location**
1. Create `/Documents/Organized_{date}/`
2. Upload entire new structure there
3. Keep original intact

**Strategy C: Upload ZIP Only**
1. Upload ZIP to specified location
2. User extracts manually

### Error Handling
- Resume failed uploads
- Track upload progress
- Handle conflicts (rename vs overwrite)
- Cleanup on partial failure

---

## Workflow 4: Webhook Receiver

### Purpose
Receive callbacks from the Docker container at various stages.

### Endpoints

```
POST /webhook/processing-started
POST /webhook/phase-complete
POST /webhook/review-required
POST /webhook/processing-complete
POST /webhook/processing-failed
```

### Flow
```
Webhook Received
    │
    ▼
Parse Payload
    │
    ▼
Update Database
    │
    ▼
Trigger Next Action (if applicable)
```

### Payload Formats

**Processing Started**
```json
{
  "event": "processing_started",
  "job_id": "uuid",
  "timestamp": "ISO8601"
}
```

**Phase Complete**
```json
{
  "event": "phase_complete",
  "job_id": "uuid",
  "phase": "indexing|deduplicating|versioning|organizing",
  "stats": {
    "files_processed": 100,
    "duration_seconds": 45
  }
}
```

**Review Required**
```json
{
  "event": "review_required",
  "job_id": "uuid",
  "report_path": "/data/reports/abc123_review.html",
  "summary": {
    "total_files": 500,
    "duplicates": 20,
    "versions": 15,
    "changes_planned": 300
  }
}
```

**Processing Complete**
```json
{
  "event": "processing_complete",
  "job_id": "uuid",
  "output_path": "/data/output/organized_abc123.zip",
  "stats": {...}
}
```

**Processing Failed**
```json
{
  "event": "processing_failed",
  "job_id": "uuid",
  "error": "Error message",
  "phase": "organizing",
  "partial_output": "/data/output/partial_abc123.zip"
}
```

### Required Nodes

1. **Webhook Node** - Multiple paths

2. **Switch Node** - Route by event type

3. **Postgres Nodes** - Update job status

4. **IF Nodes** - Conditional logic (e.g., auto-approve, notify)

5. **HTTP Request** - Trigger upload workflow

6. **Email/Slack** - Notifications

---

## n8n Workflow JSON Structure

```json
{
  "name": "Workflow Name",
  "nodes": [
    {
      "parameters": { ... },
      "id": "unique-id",
      "name": "Node Name",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [x, y],
      "credentials": { ... }
    }
  ],
  "connections": {
    "Node Name": {
      "main": [
        [
          { "node": "Next Node", "type": "main", "index": 0 }
        ]
      ]
    }
  },
  "settings": { "executionOrder": "v1" },
  "tags": [{ "name": "Document Organizer" }]
}
```

## Credentials Setup

### Postgres Credential
```json
{
  "host": "{{ $env.POSTGRES_HOST }}",
  "port": 5432,
  "database": "{{ $env.POSTGRES_DB }}",
  "user": "{{ $env.POSTGRES_USER }}",
  "password": "{{ $env.POSTGRES_PASSWORD }}"
}
```

### Microsoft OAuth (if using n8n's built-in)
- Configure in n8n UI
- Requires: client_id, client_secret, tenant_id
- Scope: Files.ReadWrite.All, Sites.ReadWrite.All

## Rate Limiting

Microsoft Graph API limits:
- 10,000 requests per 10 minutes per app
- Implement exponential backoff
- Use batch requests where possible ($batch endpoint)

```javascript
// Retry logic in Code node
const maxRetries = 3;
for (let i = 0; i < maxRetries; i++) {
  try {
    const response = await $http.request(options);
    if (response.statusCode === 429) {
      const retryAfter = response.headers['retry-after'] || 60;
      await new Promise(r => setTimeout(r, retryAfter * 1000));
      continue;
    }
    return response;
  } catch (e) {
    if (i === maxRetries - 1) throw e;
    await new Promise(r => setTimeout(r, Math.pow(2, i) * 1000));
  }
}
```

## Files to Create

1. `/n8n/workflow_download.json` - Complete download workflow
2. `/n8n/workflow_trigger.json` - Processing trigger workflow  
3. `/n8n/workflow_upload.json` - Upload results workflow
4. `/n8n/workflow_webhook.json` - Callback receiver workflow
5. `/n8n/README.md` - Setup and configuration instructions

## Testing

1. Test with small folder first (<10 files)
2. Verify token refresh works
3. Test large file upload (>4MB)
4. Test error scenarios (network failure, API limits)
5. Verify database updates at each stage

---

Please implement all four n8n workflows as complete, importable JSON files. Include proper error handling, progress tracking, and comprehensive logging. Ensure the workflows can be imported directly into n8n and work together as a cohesive system.
