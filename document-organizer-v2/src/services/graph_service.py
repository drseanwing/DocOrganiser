"""
Microsoft Graph Service - OneDrive/SharePoint API wrapper.

Provides async interface to Microsoft Graph for:
- OneDrive file operations
- SharePoint document library access
- Folder management
- File upload/download
"""

import asyncio
import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from src.config import Settings, get_settings
import structlog

logger = structlog.get_logger("graph_service")


class GraphService:
    """
    Async wrapper for Microsoft Graph API.

    Handles:
    - OAuth2 client credentials authentication (app-only)
    - Connection management
    - Retries with exponential backoff
    - File operations (list, download, upload)
    - Folder management
    """

    def __init__(self, settings: Optional[Settings] = None):
        """
        Initialize Microsoft Graph service.

        Args:
            settings: Configuration settings (uses global if not provided)
        """
        self.settings = settings or get_settings()
        self.tenant_id = getattr(self.settings, 'ms_tenant_id', None)
        self.client_id = getattr(self.settings, 'ms_client_id', None)
        self.client_secret = getattr(self.settings, 'ms_client_secret', None)

        self.base_url = "https://graph.microsoft.com/v1.0"
        self.auth_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self.timeout = 120  # 2 minute timeout for large file operations

    def is_configured(self) -> bool:
        """
        Check if Microsoft Graph credentials are configured.

        Returns:
            True if all required credentials are present, False otherwise
        """
        return bool(self.tenant_id and self.client_id and self.client_secret)

    async def _get_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """
        Get or refresh OAuth2 access token using client credentials flow.

        Args:
            force_refresh: Force token refresh even if current token is valid

        Returns:
            Access token or None on failure
        """
        # Return cached token if still valid
        if not force_refresh and self._access_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at:
                return self._access_token

        if not self.is_configured():
            logger.error("graph_not_configured",
                        message="Microsoft Graph credentials not set")
            return None

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.auth_url,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials"
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    self._access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)

                    # Set expiry with 5-minute buffer
                    self._token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)

                    logger.info("graph_token_acquired",
                               expires_in=expires_in)
                    return self._access_token
                else:
                    error_detail = response.text[:200] if response.text else "No details"
                    logger.error("graph_auth_failed",
                                status=response.status_code,
                                error=error_detail)
                    return None

        except Exception as e:
            logger.error("graph_token_error", error=str(e))
            return None

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        content: Optional[bytes] = None,
        max_retries: int = 3
    ) -> Optional[Dict[str, Any]]:
        """
        Make an authenticated request to Microsoft Graph API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint (e.g., "/me/drive/root/children")
            params: Query parameters
            json_data: JSON request body
            content: Binary content for file uploads
            max_retries: Number of retries on failure

        Returns:
            Response JSON or None on failure
        """
        token = await self._get_access_token()
        if not token:
            return None

        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json" if json_data else "application/octet-stream"
        }

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    logger.debug("graph_request",
                                method=method,
                                endpoint=endpoint,
                                attempt=attempt + 1)

                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        params=params,
                        json=json_data,
                        content=content
                    )

                    if response.status_code in (200, 201, 204):
                        # Success - return JSON if present
                        if response.status_code == 204:  # No content
                            return {}
                        return response.json() if response.content else {}

                    elif response.status_code == 401:
                        # Token expired - refresh and retry
                        logger.warning("graph_token_expired", attempt=attempt + 1)
                        token = await self._get_access_token(force_refresh=True)
                        if token:
                            headers["Authorization"] = f"Bearer {token}"
                            continue
                        return None

                    elif response.status_code == 429:
                        # Rate limited - use retry-after header
                        retry_after = int(response.headers.get("retry-after", 30))
                        logger.warning("graph_rate_limited",
                                      retry_after=retry_after,
                                      attempt=attempt + 1)
                        await asyncio.sleep(retry_after)
                        continue

                    elif response.status_code >= 500:
                        # Server error - retry with backoff
                        logger.warning("graph_server_error",
                                      status=response.status_code,
                                      attempt=attempt + 1)
                        await asyncio.sleep(2 ** attempt)
                        continue

                    else:
                        # Client error - log and fail
                        error_detail = response.text[:200] if response.text else "No details"
                        logger.error("graph_error_response",
                                    status=response.status_code,
                                    error=error_detail,
                                    endpoint=endpoint)
                        return None

            except httpx.TimeoutException:
                logger.warning("graph_timeout",
                              attempt=attempt + 1,
                              timeout=self.timeout)
            except httpx.ConnectError as e:
                logger.error("graph_connection_error",
                            error=str(e),
                            attempt=attempt + 1)
            except Exception as e:
                logger.error("graph_error",
                            error=str(e),
                            error_type=type(e).__name__,
                            attempt=attempt + 1)

            # Exponential backoff between retries
            if attempt < max_retries - 1:
                backoff_time = 2 ** attempt
                logger.info("graph_retry_backoff",
                           seconds=backoff_time,
                           next_attempt=attempt + 2)
                await asyncio.sleep(backoff_time)

        logger.error("graph_max_retries_exceeded",
                    max_retries=max_retries,
                    endpoint=endpoint)
        return None

    async def health_check(self) -> bool:
        """
        Check if Microsoft Graph API is accessible.

        Returns:
            True if API is accessible and authenticated, False otherwise
        """
        if not self.is_configured():
            logger.warning("graph_not_configured",
                          message="Microsoft Graph credentials not set")
            return False

        try:
            # Try to access user's drive
            result = await self._make_request("GET", "/me/drive")

            if result:
                logger.info("graph_health_check_success",
                           drive_id=result.get("id"))
                return True
            return False

        except Exception as e:
            logger.error("graph_health_check_error", error=str(e))
            return False

    async def list_files(
        self,
        folder_path: Optional[str] = None,
        recursive: bool = False
    ) -> Optional[List[Dict[str, Any]]]:
        """
        List files in a OneDrive folder.

        Args:
            folder_path: Path to folder (e.g., "/Documents/Projects") or None for root
            recursive: If True, recursively list all files in subfolders

        Returns:
            List of file metadata dicts or None on failure

        Example response item:
            {
                "id": "file-id-123",
                "name": "document.pdf",
                "size": 1024000,
                "createdDateTime": "2024-01-15T10:30:00Z",
                "lastModifiedDateTime": "2024-01-20T14:45:00Z",
                "webUrl": "https://...",
                "file": {"mimeType": "application/pdf"},
                "parentReference": {"path": "/drive/root:/Documents"}
            }
        """
        if folder_path:
            # Specific folder
            endpoint = f"/me/drive/root:/{folder_path.strip('/')}:/children"
        else:
            # Root folder
            endpoint = "/me/drive/root/children"

        result = await self._make_request("GET", endpoint)

        if not result:
            return None

        files = result.get("value", [])

        if recursive:
            # Recursively get files from subfolders
            all_files = []
            for item in files:
                if "folder" in item:
                    # This is a folder - recurse into it
                    subfolder_path = item.get("parentReference", {}).get("path", "")
                    subfolder_name = item.get("name", "")
                    full_path = f"{subfolder_path}/{subfolder_name}".replace("/drive/root:", "")

                    subfiles = await self.list_files(full_path, recursive=True)
                    if subfiles:
                        all_files.extend(subfiles)
                else:
                    # This is a file
                    all_files.append(item)

            return all_files

        # Filter out folders if not recursive
        return [f for f in files if "file" in f]

    async def download_file(self, file_id: str) -> Optional[bytes]:
        """
        Download a file from OneDrive by ID.

        Args:
            file_id: The unique file ID from Graph API

        Returns:
            File content as bytes or None on failure
        """
        token = await self._get_access_token()
        if not token:
            return None

        try:
            # Get download URL
            metadata = await self._make_request("GET", f"/me/drive/items/{file_id}")
            if not metadata:
                return None

            download_url = metadata.get("@microsoft.graph.downloadUrl")
            if not download_url:
                logger.error("graph_no_download_url", file_id=file_id)
                return None

            # Download file content
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(download_url)

                if response.status_code == 200:
                    logger.info("graph_file_downloaded",
                               file_id=file_id,
                               size=len(response.content))
                    return response.content
                else:
                    logger.error("graph_download_failed",
                                status=response.status_code,
                                file_id=file_id)
                    return None

        except Exception as e:
            logger.error("graph_download_error",
                        error=str(e),
                        file_id=file_id)
            return None

    async def upload_file(
        self,
        folder_path: str,
        filename: str,
        content: bytes
    ) -> Optional[Dict[str, Any]]:
        """
        Upload a file to OneDrive.

        Args:
            folder_path: Target folder path (e.g., "/Documents/Projects")
            filename: Name for the uploaded file
            content: File content as bytes

        Returns:
            File metadata dict or None on failure
        """
        file_size = len(content)
        
        # For files < 4MB, use simple upload
        if file_size < 4 * 1024 * 1024:
            folder_path = folder_path.strip('/')
            endpoint = f"/me/drive/root:/{folder_path}/{filename}:/content"
            
            return await self._make_request(
                "PUT",
                endpoint,
                content=content
            )
        
        # For files >= 4MB, use upload session
        return await self._upload_large_file(folder_path, filename, content)
    
    async def _upload_large_file(
        self,
        folder_path: str,
        filename: str,
        content: bytes
    ) -> Optional[Dict[str, Any]]:
        """
        Upload a large file using upload session.
        
        Args:
            folder_path: Target folder path
            filename: File name
            content: File content as bytes
            
        Returns:
            File metadata dict or None on failure
        """
        try:
            folder_path = folder_path.strip('/')
            file_size = len(content)
            
            # Step 1: Create upload session
            endpoint = f"/me/drive/root:/{folder_path}/{filename}:/createUploadSession"
            session_data = await self._make_request(
                "POST",
                endpoint,
                json_data={
                    "item": {
                        "@microsoft.graph.conflictBehavior": "rename"
                    }
                }
            )
            
            if not session_data or "uploadUrl" not in session_data:
                logger.error("upload_session_creation_failed",
                           folder=folder_path,
                           filename=filename)
                return None
            
            upload_url = session_data["uploadUrl"]
            
            # Step 2: Upload in chunks (4MB chunks)
            chunk_size = 4 * 1024 * 1024  # 4MB
            offset = 0
            
            while offset < file_size:
                # Calculate chunk boundaries
                chunk_end = min(offset + chunk_size, file_size)
                chunk = content[offset:chunk_end]
                
                # Upload chunk
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.put(
                        upload_url,
                        headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{chunk_end-1}/{file_size}"
                        },
                        content=chunk
                    )
                    
                    if response.status_code == 201 or response.status_code == 200:
                        # Upload complete
                        logger.info("large_file_uploaded",
                                  filename=filename,
                                  size=file_size)
                        return response.json()
                    elif response.status_code == 202:
                        # Chunk accepted, continue
                        logger.debug("chunk_uploaded",
                                   offset=offset,
                                   chunk_size=len(chunk),
                                   total=file_size)
                        offset = chunk_end
                    else:
                        logger.error("chunk_upload_failed",
                                   status=response.status_code,
                                   offset=offset)
                        return None
            
            logger.info("large_file_upload_completed",
                       filename=filename,
                       size=file_size,
                       chunks=file_size // chunk_size + 1)
            return None  # Last response should have been 201
            
        except Exception as e:
            logger.error("large_file_upload_error",
                        error=str(e),
                        filename=filename)
            return None

    async def create_folder(
        self,
        parent_path: str,
        folder_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Create a folder in OneDrive.

        Args:
            parent_path: Parent folder path (e.g., "/Documents") or empty string for root
            folder_name: Name of the new folder

        Returns:
            Folder metadata dict or None on failure
        """
        if parent_path:
            parent_path = parent_path.strip('/')
            endpoint = f"/me/drive/root:/{parent_path}:/children"
        else:
            endpoint = "/me/drive/root/children"

        json_data = {
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "rename"
        }

        return await self._make_request(
            "POST",
            endpoint,
            json_data=json_data
        )
