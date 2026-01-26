# DocOrganiser - Admin Interface

## Overview

The Admin Interface is a web-based configuration panel that allows administrators to manage API credentials and system settings for the DocOrganiser system.

## Features

- **Centralized Configuration**: Manage all API credentials and settings in one place
- **Secure Storage**: Credentials are stored encrypted in the database
- **Connectivity Testing**: Test connections to all external services
- **User-Friendly Interface**: Modern, responsive web design
- **Real-Time Validation**: Immediate feedback on configuration changes

## Accessing the Admin Interface

### Local Development

```bash
# Start the API server
python run_server.py --host 0.0.0.0 --port 8000

# Open browser to:
http://localhost:8000/admin
```

### Production Deployment

```
https://your-domain.com/admin
```

**Note:** Access should be restricted to administrators only using authentication middleware or network-level controls.

---

## Configuration Sections

### 1. Microsoft Graph API

Configure access to OneDrive and SharePoint:

| Field | Description | Example |
|-------|-------------|---------|
| **Tenant ID** | Azure AD Tenant ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| **Client ID** | Application (Client) ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| **Client Secret** | Application Client Secret | `xxxxxxxxxxxxx` |

**How to Get These Values:**

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** → **App registrations**
3. Select your app or create a new one
4. Copy **Application (client) ID** → This is your **Client ID**
5. Copy **Directory (tenant) ID** → This is your **Tenant ID**
6. Go to **Certificates & secrets** → **New client secret**
7. Copy the secret value immediately → This is your **Client Secret**

**Required Permissions:**
- `Files.ReadWrite.All` (Application)
- `Sites.ReadWrite.All` (Application)

### 2. Ollama (Local LLM)

Configure the local Ollama service for content summarization:

| Field | Description | Default | Example |
|-------|-------------|---------|---------|
| **Ollama Base URL** | Ollama service endpoint | `http://localhost:11434` | `http://ollama:11434` |
| **Ollama Model** | Model for summarization | `llama3` | `mistral`, `mixtral` |

**Supported Models:**
- `llama3` - Recommended for general use
- `mistral` - Good balance of speed and quality
- `mixtral` - Higher quality, slower
- `llama2` - Legacy support

### 3. Claude API (Complex Reasoning)

Configure Anthropic Claude API for organization planning:

| Field | Description | Example |
|-------|-------------|---------|
| **Claude API Key** | Anthropic API key | `sk-ant-xxxxx` |
| **Claude Model** | Model for organization | `claude-3-5-sonnet-20241022` |

**Supported Models:**
- `claude-3-5-sonnet-20241022` - Recommended (best balance)
- `claude-3-opus-20240229` - Highest quality
- `claude-3-sonnet-20240229` - Good quality, faster

**Getting an API Key:**
1. Sign up at [Anthropic](https://www.anthropic.com)
2. Go to **API Keys** in your account
3. Create a new key
4. Copy and paste into the admin interface

### 4. Processing Settings

Configure default processing behavior:

| Field | Description | Default | Notes |
|-------|-------------|---------|-------|
| **Source Folder Path** | Default source folder | `/Documents/ToOrganize` | Path in SharePoint/OneDrive |
| **Output Folder Path** | Default output folder | `/Documents/Organized` | Path in SharePoint/OneDrive |
| **Notification Email** | Email for notifications | (empty) | Receives job completion emails |
| **Auto-approve** | Skip manual review | `false` | ⚠️ Use with caution |

**Auto-approve Warning:**
- When enabled, organization changes are executed automatically without human review
- Only enable if you trust the AI decisions completely
- Recommended to keep disabled for UAT and initial production use

---

## Using the Admin Interface

### Initial Setup

1. **Access the Interface:**
   ```
   http://localhost:8000/admin
   ```

2. **Configure Microsoft Graph API:**
   - Enter Tenant ID
   - Enter Client ID
   - Enter Client Secret
   - Click **Save Configuration**

3. **Configure Ollama:**
   - Update URL if Ollama is on a different host
   - Select your preferred model
   - Click **Save Configuration**

4. **Configure Claude API (Optional):**
   - Enter your Claude API key
   - Select model version
   - Click **Save Configuration**

5. **Test Connectivity:**
   - Click **Test Connections** button
   - Verify all services show green checkmarks
   - Resolve any connection issues

### Updating Configuration

1. **Modify Any Fields:**
   - Leave secret fields blank to keep existing values
   - Only enter new values if you want to update them

2. **Save Changes:**
   - Click **Save Configuration**
   - Wait for success confirmation

3. **Verify Changes:**
   - Click **Reset** to reload current configuration
   - Verify your changes were saved

### Testing Connectivity

The **Test Connections** button verifies:

| Service | Test | Success Criteria |
|---------|------|------------------|
| **Database** | Connection test | Successfully connects to PostgreSQL |
| **Ollama** | API availability | `/api/tags` endpoint responds |
| **Claude API** | API key validation | API key is valid and active |
| **Microsoft Graph** | Authentication | Successfully obtains access token |

**Interpreting Results:**

- ✓ **Success** - Service is configured correctly and accessible
- ✗ **Error** - Service is not accessible or misconfigured

**Common Errors:**

| Error | Cause | Solution |
|-------|-------|----------|
| "Connection refused" | Service not running | Start the service |
| "Authentication failed" | Invalid credentials | Verify API keys/secrets |
| "Timeout" | Service too slow | Check network connectivity |
| "Not configured" | Missing credentials | Enter required credentials |

---

## Security Best Practices

### 1. Access Control

**Restrict Access:**
- Use reverse proxy (nginx, Apache) with authentication
- Implement IP whitelisting
- Use VPN for remote access
- Consider Azure AD SSO integration

**Example nginx configuration:**

```nginx
location /admin {
    auth_basic "Restricted - Admin Only";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://localhost:8000;
}
```

### 2. Secret Management

**Storage:**
- Secrets are stored encrypted in PostgreSQL
- Database should be secured with strong password
- Use encrypted connections (SSL/TLS) to database

**Display:**
- Secrets are masked in the UI (shows `****...****`)
- Full secrets are never returned by the API
- Only accept new secrets for updates

**Rotation:**
- Rotate Azure client secrets every 6-12 months
- Rotate Claude API keys periodically
- Update immediately if compromised

### 3. HTTPS

**Always use HTTPS in production:**

```bash
# Using Let's Encrypt with certbot
certbot --nginx -d admin.yourdomain.com
```

### 4. Database Security

**Secure PostgreSQL:**
- Strong password for `doc_organizer` user
- Restrict network access (bind to localhost)
- Enable SSL connections
- Regular backups with encryption

### 5. Audit Logging

**Enable audit logging:**
- Track all configuration changes
- Log all connectivity tests
- Monitor for suspicious activity
- Set up alerts for configuration changes

---

## API Endpoints

The admin interface uses these backend API endpoints:

### GET `/admin/config`

Get current configuration (secrets masked).

**Response:**
```json
{
  "ms_tenant_id": "xxxx-xxxx-xxxx",
  "ms_client_id": "xxxx-xxxx-xxxx",
  "ms_client_secret": "****...****",
  "ollama_base_url": "http://localhost:11434",
  "ollama_model": "llama3",
  "claude_api_key": "****...****",
  "claude_model": "claude-3-5-sonnet-20241022",
  "source_folder_path": "/Documents/ToOrganize",
  "output_folder_path": "/Documents/Organized",
  "auto_approve": false,
  "notification_email": "admin@example.com",
  "is_active": true
}
```

### POST `/admin/config`

Update configuration (partial updates supported).

**Request:**
```json
{
  "ollama_base_url": "http://ollama:11434",
  "notification_email": "newadmin@example.com"
}
```

**Response:**
Returns updated configuration (secrets masked).

### POST `/admin/test-connectivity`

Test connectivity to all services.

**Response:**
```json
{
  "timestamp": "2026-01-26T03:30:00Z",
  "results": [
    {
      "service": "Database",
      "status": "success",
      "message": "Connected successfully",
      "response_time_ms": 15.3
    },
    {
      "service": "Ollama",
      "status": "success",
      "message": "Connected to http://localhost:11434",
      "response_time_ms": 89.2
    },
    {
      "service": "Claude API",
      "status": "success",
      "message": "API key validated",
      "response_time_ms": 234.5
    },
    {
      "service": "Microsoft Graph",
      "status": "success",
      "message": "Authenticated successfully",
      "response_time_ms": 567.8
    }
  ]
}
```

---

## Troubleshooting

### Admin Interface Won't Load

**Symptoms:** Browser shows 404 or blank page

**Solutions:**
1. Verify API server is running:
   ```bash
   curl http://localhost:8000/health
   ```

2. Check admin files exist:
   ```bash
   ls -la document-organizer-v2/admin/
   ```

3. Check server logs for errors

### Configuration Not Saving

**Symptoms:** Changes don't persist after saving

**Solutions:**
1. Check database connection:
   ```bash
   psql -h localhost -U doc_organizer -d document_organizer -c "SELECT 1;"
   ```

2. Verify `api_configuration` table exists:
   ```sql
   SELECT * FROM api_configuration;
   ```

3. Check server logs for SQL errors

4. Verify write permissions on database

### Connectivity Tests Failing

**Database Test Fails:**
- Check PostgreSQL is running
- Verify credentials in `.env`
- Test connection manually with `psql`

**Ollama Test Fails:**
- Verify Ollama service is running: `curl http://localhost:11434/api/tags`
- Check URL is correct (protocol, host, port)
- Verify firewall rules allow connection

**Claude API Test Fails:**
- Verify API key is valid (not masked placeholder)
- Check API key hasn't expired
- Verify internet connectivity
- Check rate limits haven't been exceeded

**Microsoft Graph Test Fails:**
- Verify all three fields (Tenant, Client ID, Secret) are set
- Check Azure AD app has correct permissions
- Verify admin consent was granted
- Test token acquisition with PowerShell:
  ```powershell
  $body = @{
      client_id     = "your-client-id"
      client_secret = "your-secret"
      scope         = "https://graph.microsoft.com/.default"
      grant_type    = "client_credentials"
  }
  $response = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/your-tenant-id/oauth2/v2.0/token" -Body $body
  $response.access_token
  ```

### Secrets Not Updating

**Symptoms:** Enter new secret but old one is still used

**Problem:** Secret field was left blank or contains masked value (`****`)

**Solution:** 
- Clear the field completely
- Enter the full new secret
- Avoid pasting masked values
- Click Save

---

## Integration with Other Components

### PowerAutomate Flows

PowerAutomate flows can read configuration from SharePoint:
- Admin interface → Database
- PowerAutomate → SharePoint lists
- Two separate configuration stores (by design)

**Keeping in Sync:**
- Manual: Copy values from admin interface to SharePoint
- Automated: Create sync flow (future enhancement)

### n8n Workflows

n8n workflows can call admin API:

```javascript
// In n8n HTTP Request node
{
  "method": "GET",
  "url": "http://processor:8000/admin/config",
  "authentication": "None"
}
```

### Docker Containers

Configuration is read from environment variables and database:
- `.env` file → Environment variables (takes precedence)
- Database → Admin interface settings (fallback)

**Precedence Order:**
1. Environment variable
2. Database configuration
3. Default value

---

## Backup and Recovery

### Backup Configuration

**Database Export:**
```bash
pg_dump -h localhost -U doc_organizer -d document_organizer \
  -t api_configuration > config_backup.sql
```

**Manual Export:**
1. Access admin interface
2. Copy all visible values to secure note
3. Store in password manager (1Password, LastPass, etc.)

### Restore Configuration

**Database Import:**
```bash
psql -h localhost -U doc_organizer -d document_organizer < config_backup.sql
```

**Manual Restore:**
1. Access admin interface
2. Enter all values from secure note
3. Click Save
4. Test connectivity

---

## Development

### Running Locally

```bash
cd document-organizer-v2

# Install dependencies
pip install -r requirements.txt

# Start database
docker-compose up -d postgres

# Run server with hot reload
python run_server.py --reload

# Access admin interface
open http://localhost:8000/admin
```

### Making Changes

**Backend (API endpoints):**
- Edit `src/api/admin.py`
- Server auto-reloads with `--reload` flag

**Frontend (HTML/CSS/JS):**
- Edit `admin/index.html`
- Refresh browser to see changes

**Database Schema:**
- Edit `database/init.sql`
- Drop and recreate database
- Or create migration script

### Testing

**Manual Testing:**
1. Fill in all fields with test data
2. Click Save
3. Click Reset - verify values persist
4. Click Test Connections - verify all pass
5. Leave fields blank - verify secrets not overwritten
6. Enter invalid values - verify error handling

**API Testing:**
```bash
# Get configuration
curl http://localhost:8000/admin/config

# Update configuration
curl -X POST http://localhost:8000/admin/config \
  -H "Content-Type: application/json" \
  -d '{"ollama_model": "mistral"}'

# Test connectivity
curl -X POST http://localhost:8000/admin/test-connectivity
```

---

## Future Enhancements

Planned improvements:

1. **User Authentication:**
   - Azure AD SSO integration
   - Role-based access control
   - Audit trail of who changed what

2. **Configuration History:**
   - Track all changes with timestamps
   - Rollback to previous configurations
   - Compare configurations

3. **Bulk Operations:**
   - Import/export configuration as JSON
   - Deploy same config to multiple environments
   - Configuration templates

4. **Advanced Testing:**
   - Test file download from SharePoint
   - Test file upload to OneDrive
   - End-to-end pipeline test

5. **Monitoring Dashboard:**
   - Real-time service health
   - Recent job statistics
   - Error rate graphs
   - Performance metrics

---

## Support

### Getting Help

- **Documentation:** See `/power-automate/README.md` for PowerAutomate integration
- **API Docs:** Visit `http://localhost:8000/docs` for interactive API documentation
- **Issues:** Report bugs on GitHub repository

### Common Questions

**Q: Can I have multiple configurations?**
A: Currently only one active configuration is supported. The latest configuration is used.

**Q: Are secrets encrypted in the database?**
A: Secrets are stored in PostgreSQL. Use database-level encryption (pgcrypto extension) for additional security.

**Q: Can I configure this via API only (no UI)?**
A: Yes! The admin interface is just a frontend. You can use the API directly with curl or scripts.

**Q: How do I reset to defaults?**
A: Delete the row from `api_configuration` table. Default values will be used.

**Q: Can I use environment variables instead?**
A: Yes! Environment variables take precedence over database configuration. Set in `.env` file or Docker environment.

---

## Changelog

### Version 1.0.0 (2026-01-26)
- Initial release
- Configuration management for all services
- Connectivity testing
- Responsive web design
- Secure secret handling
- API documentation
