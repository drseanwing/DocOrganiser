# n8n Workflows for Document Organizer

This directory contains n8n workflow JSON files for integrating the Document Organizer with OneDrive/SharePoint cloud storage.

## Overview

The workflows handle the complete cloud integration lifecycle:

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

## Workflows

### 1. workflow_download.json

**Purpose:** Download a folder from OneDrive/SharePoint and create a ZIP file.

**Triggers:**
- Manual trigger for on-demand processing
- Schedule trigger (default: every 6 hours)

**Flow:**
1. Get OAuth token from Microsoft
2. Create a processing job in the database
3. List folder contents recursively
4. Download each file
5. Create ZIP archive in `/data/input/`
6. Update job status
7. Trigger the processing workflow

### 2. workflow_trigger.json

**Purpose:** Trigger the Docker container to process a downloaded ZIP.

**Triggers:**
- Webhook from download workflow
- Schedule check (every 5 minutes) for pending ZIPs

**Flow:**
1. Find pending ZIP files in `/data/input/`
2. Verify ZIP exists and is valid
3. Trigger container via HTTP or file-based trigger
4. Update job status to "processing"

### 3. workflow_upload.json

**Purpose:** Upload the reorganized files back to OneDrive/SharePoint.

**Triggers:**
- Webhook from processing complete event

**Flow:**
1. Get OAuth token from Microsoft
2. Read the output ZIP file
3. Create folder structure in cloud
4. Upload files (with chunked upload for large files)
5. Complete job and cleanup
6. Send notifications (optional)

### 4. workflow_webhook.json

**Purpose:** Receive and process callbacks from the Docker container.

**Endpoints:**
- `POST /webhook/processing-status` - Unified endpoint for all events

**Supported Events:**
- `processing_started` - Container started processing
- `phase_complete` - A processing phase completed (indexing, deduplicating, versioning, organizing)
- `review_required` - Processing paused for human review
- `processing_complete` - Processing finished successfully
- `processing_failed` - Processing encountered an error

## Installation

### Prerequisites

1. **n8n Server** (v1.0.0+)
   ```bash
   docker run -d --name n8n -p 5678:5678 \
     -v n8n_data:/home/node/.n8n \
     n8nio/n8n
   ```

2. **PostgreSQL Database** (same as Document Organizer)

3. **Microsoft Azure App Registration** with:
   - Application (client) ID
   - Client secret
   - API permissions: `Files.ReadWrite.All`, `Sites.ReadWrite.All`

### Import Workflows

1. Open n8n web interface (http://localhost:5678)
2. Go to **Workflows** → **Add Workflow** → **Import from File**
3. Import each workflow JSON file:
   - `workflow_download.json`
   - `workflow_trigger.json`
   - `workflow_upload.json`
   - `workflow_webhook.json`

### Configure Credentials

#### PostgreSQL Credential

1. Go to **Credentials** → **Add Credential** → **Postgres**
2. Configure:
   ```
   Name: PostgreSQL
   Host: postgres (or your database host)
   Port: 5432
   Database: document_organizer
   User: doc_organizer
   Password: (your password)
   ```
3. Update the credential ID in each workflow's Postgres nodes

#### Microsoft OAuth (Optional - for built-in OAuth)

If using n8n's built-in Microsoft OAuth:
1. Go to **Credentials** → **Add Credential** → **Microsoft OAuth2 API**
2. Configure with your Azure App Registration details

## Environment Variables

Configure these environment variables in n8n:

### Microsoft Graph API

| Variable | Description | Example |
|----------|-------------|---------|
| `MS_TENANT_ID` | Azure AD Tenant ID | `12345678-1234-1234-1234-123456789abc` |
| `MS_CLIENT_ID` | App Registration Client ID | `87654321-4321-4321-4321-cba987654321` |
| `MS_CLIENT_SECRET` | App Registration Client Secret | `your-secret-here` |

### Source Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `SOURCE_TYPE` | Cloud provider type | `onedrive` or `sharepoint` |
| `SOURCE_PATH` | Folder path to process | `/Documents/ToOrganize` |
| `SOURCE_SITE_ID` | SharePoint site ID (if SharePoint) | `contoso.sharepoint.com,guid1,guid2` |

### Target Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `UPLOAD_STRATEGY` | How to upload results | `extract` or `zip_only` |
| `TARGET_PATH` | Where to upload organized files | `/Documents/Organized` |

### Notifications

| Variable | Description | Example |
|----------|-------------|---------|
| `SEND_NOTIFICATIONS` | Enable notifications | `true` or `false` |
| `NOTIFICATION_WEBHOOK_URL` | Webhook for notifications | `https://hooks.slack.com/...` |
| `REVIEW_UI_URL` | URL for review interface | `http://localhost:3000` |

### Processing Options

| Variable | Description | Example |
|----------|-------------|---------|
| `AUTO_APPROVE_REVIEW` | Auto-approve reviews | `true` or `false` |

### n8n Internal Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `N8N_HOST` | Hostname for n8n server (for internal webhooks) | `n8n` or `localhost` |
| `N8N_PORT` | Port for n8n server | `5678` |

## Setting Environment Variables in n8n

### Docker

```bash
docker run -d --name n8n \
  -e MS_TENANT_ID=your-tenant-id \
  -e MS_CLIENT_ID=your-client-id \
  -e MS_CLIENT_SECRET=your-client-secret \
  -e SOURCE_TYPE=onedrive \
  -e SOURCE_PATH=/Documents/ToOrganize \
  -p 5678:5678 \
  n8nio/n8n
```

### Docker Compose

Add to your `docker-compose.yml`:

```yaml
services:
  n8n:
    image: n8nio/n8n
    container_name: doc_organizer_n8n
    restart: unless-stopped
    environment:
      # Microsoft Graph API
      MS_TENANT_ID: ${MS_TENANT_ID}
      MS_CLIENT_ID: ${MS_CLIENT_ID}
      MS_CLIENT_SECRET: ${MS_CLIENT_SECRET}
      
      # Source Configuration
      SOURCE_TYPE: ${SOURCE_TYPE:-onedrive}
      SOURCE_PATH: ${SOURCE_PATH:-/Documents/ToOrganize}
      SOURCE_SITE_ID: ${SOURCE_SITE_ID:-}
      
      # Target Configuration
      UPLOAD_STRATEGY: ${UPLOAD_STRATEGY:-extract}
      TARGET_PATH: ${TARGET_PATH:-/Documents/Organized}
      
      # Notifications
      SEND_NOTIFICATIONS: ${SEND_NOTIFICATIONS:-false}
      NOTIFICATION_WEBHOOK_URL: ${NOTIFICATION_WEBHOOK_URL:-}
      
      # Processing
      AUTO_APPROVE_REVIEW: ${AUTO_APPROVE_REVIEW:-false}
    volumes:
      - n8n_data:/home/node/.n8n
      - ./data:/data  # Shared with processor container
    ports:
      - "5678:5678"
    networks:
      - doc_organizer_network

volumes:
  n8n_data:

networks:
  doc_organizer_network:
    external: true
```

## Webhook URLs

After activating the workflows, the following webhook URLs will be available:

| Workflow | Path | Full URL |
|----------|------|----------|
| Trigger | `/webhook/download-complete` | `http://n8n:5678/webhook/download-complete` |
| Upload | `/webhook/processing-complete` | `http://n8n:5678/webhook/processing-complete` |
| Webhook Receiver | `/webhook/processing-status` | `http://n8n:5678/webhook/processing-status` |

## Testing

### 1. Test OAuth Token

Before running full workflows, verify your Microsoft credentials work:

1. Open `workflow_download.json` in n8n
2. Disable all nodes except "Manual Trigger" and "Get OAuth Token"
3. Execute the workflow
4. Check if you receive a valid `access_token`

### 2. Test with Small Folder

1. Create a test folder in OneDrive with 5-10 small files
2. Set `SOURCE_PATH` to your test folder
3. Run the download workflow manually
4. Verify ZIP is created in `/data/input/`

### 3. Test End-to-End

1. Ensure the Document Organizer container is running
2. Run the download workflow
3. Monitor logs in n8n and the processor container
4. Verify the organized files are uploaded back

## Error Handling

All workflows include error handling:

- **Retry Logic:** HTTP requests retry 3 times with exponential backoff
- **Rate Limiting:** Microsoft Graph API limits are respected (10,000 requests per 10 minutes)
- **Job Tracking:** All operations update the `processing_jobs` table
- **Failure Recovery:** Failed jobs can be restarted from the last successful phase

## Troubleshooting

### Common Issues

#### "Token expired" errors

The OAuth token is valid for 1 hour. For long-running operations, ensure token refresh is working.

#### "Access denied" to SharePoint

Verify the app registration has the correct API permissions and admin consent.

#### Files not uploading

Check:
- File size (large files >4MB use chunked upload)
- Target path exists
- Sufficient storage quota

#### Webhook not receiving callbacks

Ensure:
- n8n is accessible from the processor container
- Workflow is activated (not just saved)
- Correct webhook URL in processor configuration

### Logging

Enable detailed logging in n8n:

```bash
docker run -d --name n8n \
  -e N8N_LOG_LEVEL=debug \
  ...
```

## Security Considerations

1. **Credentials:** Never commit credentials to version control
2. **Network:** Run n8n and processor on the same Docker network
3. **HTTPS:** Use HTTPS for production deployments
4. **Access Control:** Configure n8n user authentication

## Support

For issues specific to:
- **n8n workflows:** Check n8n documentation and community
- **Microsoft Graph API:** Check Microsoft Graph documentation
- **Document Organizer:** Check the main repository documentation

## License

Part of the Document Organizer project. See main repository for license information.
