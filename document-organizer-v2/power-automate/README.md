# DocOrganiser - Power Automate Flows

This directory contains Power Automate flow definitions for SharePoint-based configuration and authentication management.

## Overview

Since true OAuth is not available on the tenant, these flows provide a workaround using SharePoint lists to store configuration and cached tokens. The flows handle token retrieval and management transparently.

## Flows

### 1. Schema Initialization Flow (`flow_schema_init.json`)

**Purpose:** Creates the required SharePoint lists for configuration storage.

**When to Run:** Once during initial setup.

**What It Creates:**
- **DocOrganiser_Configuration** - Stores API credentials (Tenant ID, Client ID, Client Secret, Ollama URL, Claude API key, etc.)
- **DocOrganiser_TokenCache** - Caches OAuth2 access tokens for reuse
- **DocOrganiser_Jobs** - Tracks processing jobs and their status

**Required Inputs:**
```json
{
  "siteUrl": "https://yourtenant.sharepoint.com/sites/DocOrganiser",
  "tenantId": "your-azure-tenant-id",
  "clientId": "your-azure-client-id",
  "clientSecret": "your-azure-client-secret",
  "adminEmail": "admin@yourtenant.com",
  "adminGroupId": "group-id-for-admin-access"
}
```

**Security:**
- Configuration list is secured with break inheritance
- Only admin group has access
- Secrets are stored encrypted

---

### 2. Get Auth Token Flow (`flow_auth_token.json`)

**Purpose:** Retrieves OAuth2 bearer token from Azure AD using client credentials flow.

**When to Run:** 
- Automatically when token expires
- Can be triggered manually for testing

**How It Works:**
1. Reads credentials from `DocOrganiser_Configuration` list
2. Calls Azure AD token endpoint
3. Caches token in `DocOrganiser_TokenCache` list
4. Returns token for immediate use

**Required Inputs:**
```json
{
  "siteUrl": "https://yourtenant.sharepoint.com/sites/DocOrganiser",
  "adminEmail": "admin@yourtenant.com"
}
```

**Response:**
```json
{
  "success": true,
  "token": "eyJ0eXAiOiJKV1QiLCJub...",
  "token_type": "Bearer",
  "expires_in": 3599,
  "expires_at": "2026-01-26T03:45:00Z"
}
```

**Error Handling:**
- Sends email notification on failure
- Returns detailed error information
- Logs errors for troubleshooting

---

### 3. Call API With Bearer Token Flow (`flow_api_with_bearer.json`)

**Purpose:** Makes authenticated API calls using cached bearer token. Automatically refreshes expired tokens.

**When to Run:** 
- Called by other flows that need to make authenticated API requests
- Can be used as a reusable sub-flow

**How It Works:**
1. Checks if cached token is still valid
2. If expired, automatically calls "Get Auth Token" flow
3. Makes API call with bearer token in Authorization header
4. Handles 401 errors by refreshing token and retrying
5. Returns API response

**Required Inputs:**
```json
{
  "siteUrl": "https://yourtenant.sharepoint.com/sites/DocOrganiser",
  "adminEmail": "admin@yourtenant.com",
  "method": "GET|POST|PUT|DELETE",
  "apiUrl": "https://graph.microsoft.com/v1.0/me/drive/root/children",
  "requestBody": { /* optional request body */ }
}
```

**Response:**
Returns the API response with original status code and headers.

**Error Handling:**
- Automatic token refresh on 401
- Retry logic with fresh token
- Propagates API errors to caller

---

## Installation Instructions

### Prerequisites

1. **Azure AD Application** with Microsoft Graph API permissions:
   - `Files.ReadWrite.All` (Application permission)
   - `Sites.ReadWrite.All` (Application permission)
   - Admin consent granted

2. **SharePoint Site** where lists will be created

3. **Power Automate** license (included with Microsoft 365)

### Step-by-Step Setup

#### Step 1: Import Flows

1. Go to [Power Automate](https://make.powerautomate.com)
2. Click **My flows** → **Import** → **Import Package (Legacy)**
3. Upload each JSON file:
   - `flow_schema_init.json`
   - `flow_auth_token.json`
   - `flow_api_with_bearer.json`

4. For each flow:
   - Select **Create as new**
   - Configure connections (SharePoint, Office 365)
   - Click **Import**

#### Step 2: Initialize SharePoint Schema

1. Open the **"DocOrganiser - Initialize SharePoint Schema"** flow
2. Click **Run flow**
3. Provide input parameters:
   ```json
   {
     "siteUrl": "https://yourtenant.sharepoint.com/sites/DocOrganiser",
     "tenantId": "your-tenant-id-from-azure",
     "clientId": "your-client-id-from-azure",
     "clientSecret": "your-client-secret-from-azure",
     "adminEmail": "youremail@tenant.com",
     "adminGroupId": "your-admin-group-id"
   }
   ```
4. Click **Run flow**
5. Wait for completion email

#### Step 3: Test Token Retrieval

1. Open the **"DocOrganiser - Get Auth Token"** flow
2. Click **Run flow**
3. Provide inputs:
   ```json
   {
     "siteUrl": "https://yourtenant.sharepoint.com/sites/DocOrganiser",
     "adminEmail": "youremail@tenant.com"
   }
   ```
4. Verify you receive a token in the response

#### Step 4: Configure Admin Interface

1. Access the DocOrganiser admin interface (see admin/ directory)
2. The interface will read from the SharePoint configuration list
3. Update settings as needed through the UI

---

## Configuration Management

### Accessing Configuration

Configuration is stored in the `DocOrganiser_Configuration` SharePoint list:

```
https://yourtenant.sharepoint.com/sites/DocOrganiser/Lists/DocOrganiser_Configuration
```

**Fields:**
- **Title** - Configuration name (e.g., "Default Configuration")
- **TenantID** - Azure AD Tenant ID
- **ClientID** - Azure AD Application (Client) ID
- **ClientSecret** - Azure AD Client Secret (encrypted)
- **OllamaBaseURL** - Ollama service endpoint
- **OllamaModel** - Ollama model name
- **ClaudeAPIKey** - Anthropic Claude API key (encrypted)
- **ClaudeModel** - Claude model identifier
- **SourceFolderPath** - Source folder in SharePoint
- **OutputFolderPath** - Output folder in SharePoint
- **AutoApprove** - Auto-approve organization changes
- **NotificationEmail** - Email for notifications
- **IsActive** - Whether this configuration is active

### Updating Configuration

**Option 1: Via SharePoint UI**
1. Navigate to the list
2. Click on the item
3. Edit fields
4. Save

**Option 2: Via Admin Interface** (Recommended)
1. Access admin interface
2. Update fields in the form
3. Click Save
4. Changes are written to SharePoint

---

## Token Management

### Token Cache

Tokens are cached in the `DocOrganiser_TokenCache` list to avoid unnecessary authentication requests.

**Fields:**
- **AccessToken** - OAuth2 bearer token (encrypted)
- **TokenType** - Usually "Bearer"
- **ExpiresAt** - Token expiration time (UTC)
- **LastRefreshed** - Last refresh timestamp

### Token Lifecycle

1. **Initial Request:** Flow calls Azure AD token endpoint
2. **Cache:** Token stored with expiration time
3. **Reuse:** Subsequent calls use cached token if not expired
4. **Refresh:** Automatic refresh when token expires (with 5-minute buffer)
5. **Error Recovery:** On 401 errors, token is force-refreshed and request retried

### Manual Token Refresh

If needed, manually refresh the token:
1. Run the "Get Auth Token" flow
2. Or delete the cached token item (will force refresh on next use)

---

## Usage Examples

### Example 1: List Files from OneDrive

```json
// Call "Call API With Bearer Token" flow
{
  "siteUrl": "https://yourtenant.sharepoint.com/sites/DocOrganiser",
  "adminEmail": "admin@tenant.com",
  "method": "GET",
  "apiUrl": "https://graph.microsoft.com/v1.0/me/drive/root:/Documents/ToOrganize:/children"
}
```

### Example 2: Upload File to SharePoint

```json
// Call "Call API With Bearer Token" flow
{
  "siteUrl": "https://yourtenant.sharepoint.com/sites/DocOrganiser",
  "adminEmail": "admin@tenant.com",
  "method": "PUT",
  "apiUrl": "https://graph.microsoft.com/v1.0/me/drive/root:/Documents/Organized/result.zip:/content",
  "requestBody": "<binary file content>"
}
```

---

## Troubleshooting

### Error: "Failed to get OAuth token"

**Cause:** Invalid credentials or permissions

**Solutions:**
1. Verify Tenant ID, Client ID, Client Secret in configuration
2. Check Azure AD app has required permissions
3. Ensure admin consent is granted
4. Verify client secret hasn't expired

### Error: "List 'DocOrganiser_Configuration' does not exist"

**Cause:** Schema initialization flow not run

**Solution:** Run the "Initialize SharePoint Schema" flow first

### Error: "Access denied"

**Cause:** User doesn't have permission to configuration list

**Solution:** 
1. Check user is in admin group
2. Verify list permissions are correctly set
3. Re-run schema initialization if needed

### Error: "Token expired" repeatedly

**Cause:** System clock skew or expiration calculation error

**Solution:**
1. Check server time is accurate
2. Manually refresh token
3. Check token expiration buffer (default 5 minutes)

---

## Security Best Practices

1. **Secure the Configuration List:**
   - Use break inheritance
   - Grant access only to admin group
   - Enable encrypted fields for secrets

2. **Rotate Secrets Regularly:**
   - Update client secret every 6-12 months
   - Update Claude API key periodically

3. **Monitor Access:**
   - Enable audit logging on SharePoint lists
   - Review access logs regularly
   - Set up alerts for configuration changes

4. **Use Least Privilege:**
   - Azure AD app should have only required permissions
   - Don't grant user-delegated permissions if not needed

5. **Backup Configuration:**
   - Export configuration regularly
   - Store backup in secure location
   - Document recovery procedures

---

## Integration with n8n Workflows

The existing n8n workflows can be modified to call these Power Automate flows for authentication:

1. **Replace** direct OAuth calls in n8n workflows
2. **Call** the "Call API With Bearer Token" flow from n8n HTTP nodes
3. **Pass** API endpoint and method as parameters
4. **Receive** authenticated API response

This provides centralized token management and works around OAuth limitations.

---

## Support and Maintenance

### Monitoring

Check flow run history:
1. Go to Power Automate
2. Click **My flows**
3. Select flow
4. View **28-day run history**

### Updates

When updating flows:
1. Export current version as backup
2. Make changes in Power Automate designer
3. Test thoroughly with sample data
4. Export updated version to this directory
5. Update version number in JSON

### Backup

Regular backups:
1. Export flows monthly
2. Store in version control
3. Document any changes
4. Keep configuration export separate (sanitized)

---

## Related Documentation

- **Admin Interface:** See `/admin/README.md` for web UI documentation
- **n8n Workflows:** See `/n8n/README.md` for cloud integration
- **API Documentation:** See `/src/api/server.py` for backend API

---

## Changelog

### Version 1.0.0 (2026-01-26)
- Initial release
- Schema initialization flow
- Auth token retrieval flow
- API call wrapper flow with auto-refresh
- Comprehensive error handling
- Email notifications
