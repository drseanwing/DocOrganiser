"""
Claude Service - Anthropic API wrapper.

Provides async interface to Claude for:
- Organization planning
- Complex decision making
- Document analysis
"""

import asyncio
import json
import httpx
from typing import Optional

from src.config import Settings, get_settings
import structlog

logger = structlog.get_logger("claude_service")


class ClaudeService:
    """
    Async wrapper for Anthropic Claude API.
    
    Handles:
    - Connection management
    - Retries with exponential backoff
    - Response parsing
    - Rate limit handling
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        """
        Initialize Claude service.
        
        Args:
            settings: Configuration settings (uses global if not provided)
        """
        self.settings = settings or get_settings()
        self.api_key = self.settings.anthropic_api_key
        self.model = self.settings.claude_model
        self.max_tokens = self.settings.claude_max_tokens
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.timeout = 120  # 2 minute timeout for long responses
    
    def is_configured(self) -> bool:
        """Check if Claude API key is configured."""
        return bool(self.api_key)
    
    async def health_check(self) -> bool:
        """
        Check if Claude API is accessible.
        
        Returns:
            True if API is accessible, False otherwise
        """
        if not self.is_configured():
            logger.warning("claude_not_configured", 
                          message="ANTHROPIC_API_KEY not set")
            return False
        
        try:
            # Make a minimal request to test connectivity
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    self.base_url,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "Hi"}]
                    }
                )
                
                if response.status_code == 200:
                    return True
                elif response.status_code == 401:
                    logger.error("claude_auth_failed", 
                                message="Invalid API key")
                    return False
                else:
                    logger.warning("claude_health_check_failed",
                                  status=response.status_code)
                    return False
                    
        except Exception as e:
            logger.error("claude_health_check_error", error=str(e))
            return False
    
    async def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Generate a response from Claude.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt for context
            max_retries: Number of retries on failure
            
        Returns:
            Generated text or None on failure
        """
        if not self.is_configured():
            logger.error("claude_not_configured",
                        message="Cannot generate - API key not set")
            return None
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    logger.debug("claude_request",
                                attempt=attempt + 1,
                                model=self.model,
                                prompt_length=len(prompt))
                    
                    response = await client.post(
                        self.base_url,
                        headers=headers,
                        json=payload
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        content = data.get("content", [])
                        
                        if content and len(content) > 0:
                            text = content[0].get("text", "")
                            logger.info("claude_response_received",
                                       response_length=len(text),
                                       model=data.get("model"),
                                       usage=data.get("usage"))
                            return text
                        
                        logger.warning("claude_empty_response")
                        return None
                    
                    elif response.status_code == 429:
                        # Rate limited - use longer backoff
                        retry_after = int(response.headers.get("retry-after", 30))
                        logger.warning("claude_rate_limited",
                                      retry_after=retry_after,
                                      attempt=attempt + 1)
                        await asyncio.sleep(retry_after)
                        continue
                    
                    elif response.status_code == 529:
                        # Overloaded - retry with backoff
                        logger.warning("claude_overloaded", attempt=attempt + 1)
                        await asyncio.sleep(10 * (attempt + 1))
                        continue
                    
                    else:
                        error_detail = response.text[:200] if response.text else "No details"
                        logger.error("claude_error_response",
                                    status=response.status_code,
                                    error=error_detail,
                                    attempt=attempt + 1)
                    
            except httpx.TimeoutException:
                logger.warning("claude_timeout", 
                              attempt=attempt + 1,
                              timeout=self.timeout)
            except httpx.ConnectError as e:
                logger.error("claude_connection_error", 
                            error=str(e),
                            attempt=attempt + 1)
            except Exception as e:
                logger.error("claude_error",
                            error=str(e),
                            error_type=type(e).__name__,
                            attempt=attempt + 1)
            
            # Exponential backoff between retries
            if attempt < max_retries - 1:
                backoff_time = 2 ** (attempt + 1)
                logger.info("claude_retry_backoff",
                           seconds=backoff_time,
                           next_attempt=attempt + 2)
                await asyncio.sleep(backoff_time)
        
        logger.error("claude_max_retries_exceeded", max_retries=max_retries)
        return None
    
    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[dict]:
        """
        Generate a JSON response from Claude.
        
        Attempts to parse the response as JSON, handling markdown code blocks.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            max_retries: Number of retries
            
        Returns:
            Parsed JSON dict or None on failure
        """
        response = await self.generate(prompt, system_prompt, max_retries)
        
        if not response:
            return None
        
        return self._extract_json(response)
    
    def _extract_json(self, text: str) -> Optional[dict]:
        """
        Extract JSON from text, handling markdown code blocks.
        
        Args:
            text: Raw response text
            
        Returns:
            Parsed JSON dict or None
        """
        # Try direct JSON parsing first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Try to extract from markdown code block
        json_patterns = [
            # ```json ... ```
            r'```json\s*\n?(.*?)```',
            # ``` ... ```
            r'```\s*\n?(.*?)```',
            # Look for JSON object pattern
            r'(\{[\s\S]*\})',
        ]
        
        import re
        for pattern in json_patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1).strip()
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue
        
        logger.error("claude_json_parse_failed",
                    response_preview=text[:500] if len(text) > 500 else text)
        return None
