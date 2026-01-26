# DocOrganiser - Deployment Guide for UAT

## Overview

This guide provides step-by-step instructions for deploying DocOrganiser to a UAT (User Acceptance Testing) environment.

**Target Environment:**
- Docker-based deployment
- PostgreSQL database
- Ollama for local LLM
- Access to SharePoint/OneDrive via Microsoft Graph API
- Optional: Claude API for enhanced AI capabilities

---

## Prerequisites

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **OS** | Linux, macOS, or Windows | Linux (Ubuntu 20.04+) |
| **CPU** | 4 cores | 8 cores |
| **RAM** | 8 GB | 16 GB |
| **Disk** | 50 GB free | 100 GB free |
| **Network** | 10 Mbps | 100 Mbps |

### Software Requirements

- [ ] **Docker**: Version 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- [ ] **Docker Compose**: Version 2.0+ ([Install Docker Compose](https://docs.docker.com/compose/install/))
- [ ] **Git**: Version 2.25+ ([Install Git](https://git-scm.com/downloads))
- [ ] **Python**: 3.11+ (for local testing)
- [ ] **Access to Azure Portal** (for Microsoft Graph API setup)

### API Credentials Required

- [ ] **Azure AD Application** (Tenant ID, Client ID, Client Secret)
- [ ] **Claude API Key** (optional but recommended)
- [ ] **SharePoint Site** URL and permissions

---

## Step 1: Azure AD Application Setup

### 1.1 Create Application

1. Navigate to [Azure Portal](https://portal.azure.com)
2. Go to **Azure Active Directory** → **App registrations**
3. Click **New registration**
4. Fill in details:
   - **Name**: `DocOrganiser UAT`
   - **Supported account types**: Single tenant
   - **Redirect URI**: Leave blank
5. Click **Register**

### 1.2 Note Application Details

Copy and save securely:
- **Application (client) ID**: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
- **Directory (tenant) ID**: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

### 1.3 Create Client Secret

1. In your app registration, go to **Certificates & secrets**
2. Click **New client secret**
3. Description: `UAT Secret`
4. Expires: `24 months` (or as per policy)
5. Click **Add**
6. **IMPORTANT**: Copy the secret value immediately (you won't see it again)

### 1.4 Configure API Permissions

1. Go to **API permissions**
2. Click **Add a permission**
3. Select **Microsoft Graph**
4. Select **Application permissions**
5. Add these permissions:
   - `Files.ReadWrite.All`
   - `Sites.ReadWrite.All`
6. Click **Add permissions**
7. Click **Grant admin consent for [your tenant]**
8. Verify checkmarks appear next to permissions

### 1.5 Verification

Test the credentials with PowerShell:

```powershell
$tenantId = "your-tenant-id"
$clientId = "your-client-id"
$clientSecret = "your-client-secret"

$body = @{
    client_id     = $clientId
    client_secret = $clientSecret
    scope         = "https://graph.microsoft.com/.default"
    grant_type    = "client_credentials"
}

$response = Invoke-RestMethod -Method Post `
    -Uri "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/token" `
    -Body $body

if ($response.access_token) {
    Write-Host "✓ Success! Token acquired" -ForegroundColor Green
} else {
    Write-Host "✗ Failed to acquire token" -ForegroundColor Red
}
```

---

## Step 2: SharePoint Site Setup

### 2.1 Create or Select Site

1. Go to SharePoint admin center
2. Create new site or use existing
3. Note the site URL: `https://yourtenant.sharepoint.com/sites/DocOrganiser`

### 2.2 Create Folder Structure

Create these folders in the site document library:

```
/Documents/
  ├── ToOrganize/      (Source files)
  ├── Organized/       (Output files)
  └── Archive/         (Backups)
```

### 2.3 Verify Permissions

The Azure AD application should have access to read/write files in the site.

Test with PowerShell (after obtaining token in Step 1.5):

```powershell
$siteUrl = "https://yourtenant.sharepoint.com/sites/DocOrganiser"
$apiUrl = "https://graph.microsoft.com/v1.0/sites/$siteUrl"

$headers = @{
    Authorization = "Bearer $($response.access_token)"
}

$site = Invoke-RestMethod -Uri $apiUrl -Headers $headers

if ($site.id) {
    Write-Host "✓ Site accessible" -ForegroundColor Green
} else {
    Write-Host "✗ Cannot access site" -ForegroundColor Red
}
```

---

## Step 3: Server Provisioning

### Option A: Linux Server (Recommended)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installations
docker --version
docker-compose --version

# Install Git
sudo apt install git -y

# Logout and login for docker group to take effect
```

### Option B: Windows Server

1. Install Docker Desktop for Windows
2. Enable WSL 2 backend
3. Install Git for Windows
4. Open PowerShell as Administrator

### Option C: macOS

```bash
# Install Homebrew if not installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Docker Desktop
brew install --cask docker

# Install Git
brew install git
```

---

## Step 4: Clone Repository

```bash
# Clone repository
git clone https://github.com/drseanwing/DocOrganiser.git

# Navigate to application directory
cd DocOrganiser/document-organizer-v2

# Verify files
ls -la
# Should see: docker-compose.yml, Dockerfile, requirements.txt, etc.
```

---

## Step 5: Configuration

### 5.1 Create Environment File

```bash
# Copy example environment file
cp .env.example .env

# Edit environment file
nano .env
```

### 5.2 Configure .env File

**Minimum Configuration:**

```bash
# Database
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=document_organizer
POSTGRES_USER=doc_organizer
POSTGRES_PASSWORD=ChangeMeToSecurePassword123!

# Ollama
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=llama3

# Claude API (optional but recommended)
ANTHROPIC_API_KEY=sk-ant-your-api-key-here
CLAUDE_MODEL=claude-3-5-sonnet-20241022

# Microsoft Graph API
MS_TENANT_ID=your-tenant-id-here
MS_CLIENT_ID=your-client-id-here
MS_CLIENT_SECRET=your-client-secret-here

# Processing
BATCH_SIZE=50
REVIEW_REQUIRED=true
DRY_RUN=false

# Paths
DATA_INPUT_PATH=/data/input
DATA_SOURCE_PATH=/data/source
DATA_WORKING_PATH=/data/working
DATA_OUTPUT_PATH=/data/output
DATA_REPORTS_PATH=/data/reports

# Logging
LOG_LEVEL=INFO

# Callback (optional - for n8n integration)
CALLBACK_URL=http://n8n:5678/webhook/processing-callback
```

**Important:** Replace all placeholder values with actual credentials.

### 5.3 Secure the .env File

```bash
# Restrict permissions
chmod 600 .env

# Ensure it's in .gitignore
echo ".env" >> .gitignore
```

---

## Step 6: Deploy Services

### 6.1 Review Docker Compose

```bash
# View services that will be deployed
cat docker-compose.yml

# Should see:
# - postgres (database)
# - ollama (local LLM)
# - processor (main application)
```

### 6.2 Start Services

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Check service status
docker-compose ps
```

Expected output:
```
NAME                  STATUS    PORTS
doc_organizer_postgres   Up      5432
doc_organizer_ollama     Up      11434
doc_organizer_processor  Up      8000
```

### 6.3 Verify Database

```bash
# Connect to database
docker exec -it doc_organizer_postgres psql -U doc_organizer -d document_organizer

# Check tables
\dt

# Should see tables:
# - processing_jobs
# - document_items
# - duplicate_groups
# - version_chains
# - api_configuration
# - etc.

# Exit
\q
```

### 6.4 Pull Ollama Models

```bash
# Enter Ollama container
docker exec -it doc_organizer_ollama bash

# Pull models
ollama pull llama3
ollama pull mistral  # optional alternative

# List installed models
ollama list

# Exit
exit
```

---

## Step 7: Initial Configuration

### 7.1 Access Admin Interface

1. Open browser: `http://your-server-ip:8000/admin`
2. You should see the admin configuration page

### 7.2 Configure via Admin UI

1. **Microsoft Graph API:**
   - Enter Tenant ID
   - Enter Client ID
   - Enter Client Secret
   
2. **Ollama:**
   - Verify URL: `http://ollama:11434`
   - Select model: `llama3`

3. **Claude API:**
   - Enter API key (if you have one)
   - Select model

4. **Processing Settings:**
   - Source folder: `/Documents/ToOrganize`
   - Output folder: `/Documents/Organized`
   - Email: your-email@company.com
   - Auto-approve: **OFF** (leave unchecked for UAT)

5. **Save Configuration**

6. **Test Connections:**
   - Click "Test Connections"
   - Verify all services show green checkmarks

---

## Step 8: PowerAutomate Flows Setup (Optional)

### 8.1 Import Flows

1. Go to [Power Automate](https://make.powerautomate.com)
2. Click **My flows** → **Import** → **Import Package**
3. Upload flows from `power-automate/` directory:
   - `flow_schema_init.json`
   - `flow_auth_token.json`
   - `flow_api_with_bearer.json`

### 8.2 Configure Connections

For each flow:
1. Select **Create as new**
2. Set up connections:
   - SharePoint connection
   - Office 365 connection
3. Click **Import**

### 8.3 Run Schema Initialization

1. Open **"DocOrganiser - Initialize SharePoint Schema"** flow
2. Click **Run flow**
3. Provide inputs:
   ```json
   {
     "siteUrl": "https://yourtenant.sharepoint.com/sites/DocOrganiser",
     "tenantId": "your-tenant-id",
     "clientId": "your-client-id",
     "clientSecret": "your-client-secret",
     "adminEmail": "admin@company.com",
     "adminGroupId": "your-admin-group-id"
   }
   ```
4. Wait for completion email

### 8.4 Test Token Flow

1. Open **"DocOrganiser - Get Auth Token"** flow
2. Run manually
3. Verify token received

---

## Step 9: Test Deployment

### 9.1 API Health Check

```bash
curl http://localhost:8000/health

# Expected response:
{
  "status": "healthy",
  "version": "2.0.0",
  "timestamp": "2026-01-26T..."
}
```

### 9.2 Admin API Test

```bash
# Get configuration
curl http://localhost:8000/admin/config

# Test connectivity
curl -X POST http://localhost:8000/admin/test-connectivity
```

### 9.3 Simple Processing Test

1. **Create Test ZIP:**
   ```bash
   # Create test directory with sample files
   mkdir -p /tmp/test-docs
   echo "Test document 1" > /tmp/test-docs/doc1.txt
   echo "Test document 2" > /tmp/test-docs/doc2.txt
   cp /tmp/test-docs/doc1.txt /tmp/test-docs/doc1_copy.txt  # duplicate
   
   # Create ZIP
   cd /tmp
   zip -r test-docs.zip test-docs/
   
   # Copy to input directory
   docker cp test-docs.zip doc_organizer_processor:/data/input/
   ```

2. **Trigger Processing:**
   ```bash
   curl -X POST http://localhost:8000/webhook/job \
     -H "Content-Type: application/json" \
     -d '{"source_path": "/data/input/test-docs.zip"}'
   ```

3. **Check Status:**
   ```bash
   # Use job_id from previous response
   curl http://localhost:8000/jobs/{job_id}/status
   ```

4. **View Logs:**
   ```bash
   docker-compose logs -f processor
   ```

---

## Step 10: Production Hardening

### 10.1 Enable HTTPS

**Option A: Using Nginx Reverse Proxy**

```nginx
# /etc/nginx/sites-available/docorganiser
server {
    listen 80;
    server_name docorganiser.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name docorganiser.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/docorganiser.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/docorganiser.yourdomain.com/privkey.pem;

    # Admin interface - require authentication
    location /admin {
        auth_basic "Restricted - Admin Only";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API endpoints
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Option B: Let's Encrypt**

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d docorganiser.yourdomain.com

# Auto-renewal
sudo certbot renew --dry-run
```

### 10.2 Configure Firewall

```bash
# UFW (Ubuntu)
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable

# Verify
sudo ufw status
```

### 10.3 Set Up Monitoring

**Option A: Using Docker Health Checks**

Already configured in `docker-compose.yml`.

**Option B: External Monitoring**

Set up monitoring with:
- UptimeRobot (uptime monitoring)
- Datadog/New Relic (performance monitoring)
- Grafana + Prometheus (custom metrics)

### 10.4 Configure Backups

```bash
# Database backup script
cat > /usr/local/bin/backup-docorganiser.sh << 'EOF'
#!/bin/bash
BACKUP_DIR=/var/backups/docorganiser
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup database
docker exec doc_organizer_postgres pg_dump -U doc_organizer document_organizer | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Backup configuration
docker exec doc_organizer_processor tar czf - /data | cat > $BACKUP_DIR/data_$DATE.tar.gz

# Keep only last 7 days
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
EOF

# Make executable
sudo chmod +x /usr/local/bin/backup-docorganiser.sh

# Schedule daily backup
(crontab -l 2>/dev/null; echo "0 2 * * * /usr/local/bin/backup-docorganiser.sh") | crontab -
```

### 10.5 Enable Logging

```bash
# Configure log rotation
sudo cat > /etc/logrotate.d/docorganiser << 'EOF'
/var/log/docorganiser/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 root root
    sharedscripts
}
EOF
```

---

## Step 11: Documentation and Handoff

### 11.1 Create Runbook

Document:
- [ ] Server access details
- [ ] Admin credentials (in password manager)
- [ ] Restart procedures
- [ ] Backup/restore procedures
- [ ] Troubleshooting guide
- [ ] Emergency contacts

### 11.2 Train Users

- [ ] Schedule admin training session
- [ ] Provide access to documentation
- [ ] Walk through test scenario
- [ ] Answer questions

### 11.3 Handoff Checklist

- [ ] All services running
- [ ] All tests passing
- [ ] Documentation complete
- [ ] Credentials transferred securely
- [ ] Backup tested
- [ ] Monitoring configured
- [ ] Support plan established

---

## Troubleshooting

### Services Won't Start

```bash
# Check logs
docker-compose logs

# Check disk space
df -h

# Check Docker resources
docker system df

# Restart services
docker-compose restart
```

### Database Connection Failed

```bash
# Check PostgreSQL logs
docker logs doc_organizer_postgres

# Test connection
docker exec -it doc_organizer_postgres psql -U doc_organizer -d document_organizer

# Reset password if needed
docker exec -it doc_organizer_postgres psql -U postgres
ALTER USER doc_organizer WITH PASSWORD 'new-password';
```

### Ollama Not Responding

```bash
# Check if Ollama is running
docker exec -it doc_organizer_ollama ollama list

# Restart Ollama
docker-compose restart ollama

# Pull models again
docker exec -it doc_organizer_ollama ollama pull llama3
```

### Admin Interface 404

```bash
# Check if admin files exist
docker exec -it doc_organizer_processor ls -la /app/admin/

# Check server logs
docker logs doc_organizer_processor

# Restart processor
docker-compose restart processor
```

### Microsoft Graph API Errors

```bash
# Test token acquisition
docker exec -it doc_organizer_processor python -c "
from src.services.graph_service import GraphService
import asyncio

async def test():
    gs = GraphService()
    token = await gs._get_access_token()
    print(f'Token: {token[:20]}...')

asyncio.run(test())
"
```

---

## Rollback Procedure

If deployment fails:

```bash
# Stop services
docker-compose down

# Restore previous version
git checkout previous-stable-tag

# Restore database from backup
gunzip < /var/backups/docorganiser/db_latest.sql.gz | \
  docker exec -i doc_organizer_postgres psql -U doc_organizer -d document_organizer

# Start services
docker-compose up -d

# Verify
curl http://localhost:8000/health
```

---

## Support

### Getting Help

- **Documentation**: `/document-organizer-v2/README.md`
- **Admin Guide**: `/document-organizer-v2/admin/README.md`
- **UAT Checklist**: `/UAT_CHECKLIST.md`
- **GitHub Issues**: https://github.com/drseanwing/DocOrganiser/issues

### Emergency Contacts

- **Technical Lead**: [Name] - [Email] - [Phone]
- **DevOps**: [Name] - [Email] - [Phone]
- **On-Call**: [Rotation Schedule]

---

## Appendix

### A. Environment Variables Reference

See `.env.example` for complete list with descriptions.

### B. Port Reference

| Port | Service | Protocol |
|------|---------|----------|
| 5432 | PostgreSQL | TCP |
| 8000 | API Server | HTTP |
| 11434 | Ollama | HTTP |

### C. Default Credentials

**Database:**
- User: `doc_organizer`
- Password: Set in `.env`
- Database: `document_organizer`

**Note:** Change all default passwords before production use.

---

**Version**: 1.0.0  
**Last Updated**: 2026-01-26  
**Deployment Lead**: __________________
