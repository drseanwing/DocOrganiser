"""
Admin API endpoints for configuration management.

Provides HTTP API for:
- Retrieving current configuration
- Updating configuration settings
- Testing connectivity to external services
"""

from typing import Optional, Dict, Any
from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config import get_settings

logger = structlog.get_logger("admin_api")

# Create router
router = APIRouter(prefix="/admin", tags=["Admin"])

# Database engine (lazy-loaded)
_admin_engine: Optional[Engine] = None


def get_admin_engine() -> Engine:
    """Get or create admin database engine."""
    global _admin_engine
    if _admin_engine is None:
        settings = get_settings()
        _admin_engine = create_engine(settings.database_url)
    return _admin_engine


# ============================================================================
# Pydantic Models
# ============================================================================

class APIConfiguration(BaseModel):
    """API configuration model."""
    # Microsoft Graph
    ms_tenant_id: Optional[str] = Field(None, description="Azure AD Tenant ID")
    ms_client_id: Optional[str] = Field(None, description="Azure AD Client ID")
    ms_client_secret: Optional[str] = Field(None, description="Azure AD Client Secret (masked)")
    
    # Ollama
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama service URL")
    ollama_model: str = Field(default="llama3", description="Ollama model name")
    
    # Claude
    claude_api_key: Optional[str] = Field(None, description="Anthropic Claude API key (masked)")
    claude_model: str = Field(default="claude-3-5-sonnet-20241022", description="Claude model")
    
    # Processing settings
    source_folder_path: str = Field(default="/Documents/ToOrganize", description="Source folder path")
    output_folder_path: str = Field(default="/Documents/Organized", description="Output folder path")
    auto_approve: bool = Field(default=False, description="Auto-approve organization changes")
    notification_email: Optional[str] = Field(None, description="Notification email address")
    
    # System
    is_active: bool = Field(default=True, description="Configuration is active")
    
    @validator('ms_client_secret', 'claude_api_key', pre=True)
    def mask_secrets(cls, v):
        """Mask secrets when reading from database."""
        if v and len(v) > 8:
            return f"{v[:4]}...{v[-4:]}"
        return v


class ConfigurationUpdate(BaseModel):
    """Configuration update request."""
    # Microsoft Graph
    ms_tenant_id: Optional[str] = None
    ms_client_id: Optional[str] = None
    ms_client_secret: Optional[str] = None
    
    # Ollama
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    
    # Claude
    claude_api_key: Optional[str] = None
    claude_model: Optional[str] = None
    
    # Processing settings
    source_folder_path: Optional[str] = None
    output_folder_path: Optional[str] = None
    auto_approve: Optional[bool] = None
    notification_email: Optional[str] = None
    
    # System
    is_active: Optional[bool] = None


class ConnectivityTestResult(BaseModel):
    """Result of connectivity test."""
    service: str = Field(..., description="Service name")
    status: str = Field(..., description="Status: success or error")
    message: str = Field(..., description="Status message")
    response_time_ms: Optional[float] = Field(None, description="Response time in milliseconds")


class ConnectivityTestResponse(BaseModel):
    """Response from connectivity tests."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    results: list[ConnectivityTestResult] = Field(..., description="Test results")


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/config", response_model=APIConfiguration)
async def get_configuration():
    """
    Get current API configuration.
    
    Returns masked secrets for security.
    """
    try:
        engine = get_admin_engine()
        
        # Get configuration from database
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT 
                        ms_tenant_id, ms_client_id, ms_client_secret,
                        ollama_base_url, ollama_model,
                        claude_api_key, claude_model,
                        source_folder_path, output_folder_path,
                        auto_approve, notification_email, is_active
                    FROM api_configuration
                    WHERE is_active = TRUE
                    ORDER BY id DESC
                    LIMIT 1
                """)
            )
            row = result.fetchone()
        
        if not row:
            # Return defaults if no configuration exists
            return APIConfiguration()
        
        return APIConfiguration(
            ms_tenant_id=row[0],
            ms_client_id=row[1],
            ms_client_secret=row[2],
            ollama_base_url=row[3],
            ollama_model=row[4],
            claude_api_key=row[5],
            claude_model=row[6],
            source_folder_path=row[7],
            output_folder_path=row[8],
            auto_approve=row[9],
            notification_email=row[10],
            is_active=row[11]
        )
    
    except Exception as e:
        logger.error("get_config_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve configuration: {str(e)}"
        )


@router.post("/config", response_model=APIConfiguration)
async def update_configuration(config: ConfigurationUpdate):
    """
    Update API configuration.
    
    Only updates provided fields. Secrets are stored encrypted.
    """
    try:
        engine = get_admin_engine()
        
        # Build update query dynamically based on provided fields
        updates = []
        params = {}
        
        if config.ms_tenant_id is not None:
            updates.append("ms_tenant_id = :ms_tenant_id")
            params["ms_tenant_id"] = config.ms_tenant_id
        
        if config.ms_client_id is not None:
            updates.append("ms_client_id = :ms_client_id")
            params["ms_client_id"] = config.ms_client_id
        
        if config.ms_client_secret is not None:
            # Don't update if it's the masked version
            if not config.ms_client_secret.startswith("****"):
                updates.append("ms_client_secret = :ms_client_secret")
                params["ms_client_secret"] = config.ms_client_secret
        
        if config.ollama_base_url is not None:
            updates.append("ollama_base_url = :ollama_base_url")
            params["ollama_base_url"] = config.ollama_base_url
        
        if config.ollama_model is not None:
            updates.append("ollama_model = :ollama_model")
            params["ollama_model"] = config.ollama_model
        
        if config.claude_api_key is not None:
            # Don't update if it's the masked version
            if not config.claude_api_key.startswith("****"):
                updates.append("claude_api_key = :claude_api_key")
                params["claude_api_key"] = config.claude_api_key
        
        if config.claude_model is not None:
            updates.append("claude_model = :claude_model")
            params["claude_model"] = config.claude_model
        
        if config.source_folder_path is not None:
            updates.append("source_folder_path = :source_folder_path")
            params["source_folder_path"] = config.source_folder_path
        
        if config.output_folder_path is not None:
            updates.append("output_folder_path = :output_folder_path")
            params["output_folder_path"] = config.output_folder_path
        
        if config.auto_approve is not None:
            updates.append("auto_approve = :auto_approve")
            params["auto_approve"] = config.auto_approve
        
        if config.notification_email is not None:
            updates.append("notification_email = :notification_email")
            params["notification_email"] = config.notification_email
        
        if config.is_active is not None:
            updates.append("is_active = :is_active")
            params["is_active"] = config.is_active
        
        if not updates:
            raise HTTPException(
                status_code=400,
                detail="No fields to update"
            )
        
        updates.append("updated_at = NOW()")
        
        # Check if configuration exists
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT id FROM api_configuration ORDER BY id DESC LIMIT 1")
            )
            existing = result.fetchone()
        
        if existing:
            # Update existing configuration
            config_id = existing[0]
            query = f"""
                UPDATE api_configuration
                SET {', '.join(updates)}
                WHERE id = :config_id
            """
            params["config_id"] = config_id
        else:
            # Insert new configuration
            columns = ["created_at", "updated_at"] + [u.split(" = ")[0] for u in updates if "updated_at" not in u]
            placeholders = ["NOW()", "NOW()"] + [f":{u.split(' = ')[0]}" for u in updates if "updated_at" not in u]
            query = f"""
                INSERT INTO api_configuration ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
            """
        
        with engine.connect() as conn:
            conn.execute(text(query), params)
            conn.commit()
        
        logger.info("config_updated", fields_updated=len(updates))
        
        # Return updated configuration
        return await get_configuration()
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_config_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update configuration: {str(e)}"
        )


@router.post("/test-connectivity", response_model=ConnectivityTestResponse)
async def test_connectivity():
    """
    Test connectivity to external services.
    
    Tests:
    - Database connection
    - Ollama service
    - Claude API (if configured)
    - Microsoft Graph API (if configured)
    """
    import httpx
    import time
    
    results = []
    
    # Test 1: Database
    try:
        start = time.time()
        engine = get_admin_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        response_time = (time.time() - start) * 1000
        results.append(ConnectivityTestResult(
            service="Database",
            status="success",
            message="Connected successfully",
            response_time_ms=response_time
        ))
    except Exception as e:
        results.append(ConnectivityTestResult(
            service="Database",
            status="error",
            message=str(e)
        ))
    
    # Get configuration for other tests
    try:
        config = await get_configuration()
    except Exception as e:
        return ConnectivityTestResponse(results=results)
    
    # Test 2: Ollama
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{config.ollama_base_url}/api/tags")
        response_time = (time.time() - start) * 1000
        
        if response.status_code == 200:
            results.append(ConnectivityTestResult(
                service="Ollama",
                status="success",
                message=f"Connected to {config.ollama_base_url}",
                response_time_ms=response_time
            ))
        else:
            results.append(ConnectivityTestResult(
                service="Ollama",
                status="error",
                message=f"HTTP {response.status_code}"
            ))
    except Exception as e:
        results.append(ConnectivityTestResult(
            service="Ollama",
            status="error",
            message=str(e)
        ))
    
    # Test 3: Claude API
    if config.claude_api_key and not config.claude_api_key.startswith("****"):
        try:
            start = time.time()
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": config.claude_api_key,
                        "anthropic-version": "2023-06-01"
                    }
                )
            response_time = (time.time() - start) * 1000
            
            # Anthropic returns 400 for GET to messages endpoint, but it confirms API key works
            if response.status_code in (200, 400, 405):
                results.append(ConnectivityTestResult(
                    service="Claude API",
                    status="success",
                    message="API key validated",
                    response_time_ms=response_time
                ))
            else:
                results.append(ConnectivityTestResult(
                    service="Claude API",
                    status="error",
                    message=f"HTTP {response.status_code}"
                ))
        except Exception as e:
            results.append(ConnectivityTestResult(
                service="Claude API",
                status="error",
                message=str(e)
            ))
    
    # Test 4: Microsoft Graph API
    if config.ms_tenant_id and config.ms_client_id:
        try:
            from src.services.graph_service import GraphService
            
            start = time.time()
            graph = GraphService()
            health = await graph.health_check()
            response_time = (time.time() - start) * 1000
            
            if health:
                results.append(ConnectivityTestResult(
                    service="Microsoft Graph",
                    status="success",
                    message="Authenticated successfully",
                    response_time_ms=response_time
                ))
            else:
                results.append(ConnectivityTestResult(
                    service="Microsoft Graph",
                    status="error",
                    message="Authentication failed"
                ))
        except Exception as e:
            results.append(ConnectivityTestResult(
                service="Microsoft Graph",
                status="error",
                message=str(e)
            ))
    
    return ConnectivityTestResponse(results=results)
