"""
Claude Service - Anthropic API wrapper.

Provides async interface to Claude for:
- Organization planning
- Document analysis
- Strategic decision making
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
    Async wrapper for Claude API (Anthropic).
    
    Handles:
    - Connection management
    - Retries with exponential backoff
    - Response parsing
    - Rate limiting
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.api_key = self.settings.anthropic_api_key
        self.model = self.settings.claude_model
        self.max_tokens = self.settings.claude_max_tokens
        self.base_url = "https://api.anthropic.com/v1/messages"
        
        if not self.api_key:
            logger.warning("anthropic_api_key_not_set")
    
    async def health_check(self) -> bool:
        """Check if Claude API is accessible."""
        if not self.api_key:
            logger.error("health_check_failed", reason="api_key_not_set")
            return False
        
        try:
            # Simple test call with minimal tokens
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
                        "messages": [{"role": "user", "content": "test"}]
                    }
                )
                return response.status_code in [200, 429]  # 429 = rate limited but API works
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return False
    
    async def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        max_retries: int = 3,
        temperature: float = 0.3
    ) -> Optional[str]:
        """
        Generate a response from Claude.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt for context
            max_retries: Number of retries on failure
            temperature: Response randomness (0.0-1.0)
            
        Returns:
            Generated text or None on failure
        """
        if not self.api_key:
            logger.error("generate_failed", reason="api_key_not_set")
            return None
        
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        self.base_url,
                        headers=headers,
                        json=payload
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        # Extract text from content blocks
                        content = data.get("content", [])
                        if content and isinstance(content, list):
                            # Concatenate all text blocks
                            text_blocks = [
                                block.get("text", "") 
                                for block in content 
                                if block.get("type") == "text"
                            ]
                            return "".join(text_blocks)
                        return None
                    
                    # Handle rate limiting
                    elif response.status_code == 429:
                        retry_after = int(response.headers.get("retry-after", 60))
                        logger.warning("claude_rate_limited", 
                                      attempt=attempt + 1,
                                      retry_after=retry_after)
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_after)
                        continue
                    
                    # Other errors
                    else:
                        logger.warning("claude_error_response", 
                                      status=response.status_code,
                                      attempt=attempt + 1,
                                      body=response.text[:500])
                        
            except httpx.TimeoutException:
                logger.warning("claude_timeout", attempt=attempt + 1)
            except Exception as e:
                logger.error("claude_error", error=str(e), attempt=attempt + 1)
            
            # Exponential backoff (but not on last attempt)
            if attempt < max_retries - 1:
                backoff = min(2 ** attempt, 60)  # Cap at 60 seconds
                await asyncio.sleep(backoff)
        
        logger.error("claude_generate_failed", attempts=max_retries)
        return None
    
    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[dict]:
        """
        Generate a JSON response from Claude.
        
        Attempts to extract JSON from the response, handling markdown code blocks.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            max_retries: Number of retries
            
        Returns:
            Parsed JSON dict or None on failure
        """
        response_text = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_retries=max_retries,
            temperature=0.3  # Lower temperature for structured output
        )
        
        if not response_text:
            return None
        
        # Try to extract JSON from response
        try:
            # First, try direct parsing
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract from markdown code blocks
            try:
                # Look for ```json ... ``` or ``` ... ```
                import re
                json_match = re.search(
                    r'```(?:json)?\s*\n?(.*?)\n?```',
                    response_text,
                    re.DOTALL
                )
                if json_match:
                    json_str = json_match.group(1).strip()
                    return json.loads(json_str)
                
                # If no code block, try to find JSON object
                json_match = re.search(
                    r'\{.*\}',
                    response_text,
                    re.DOTALL
                )
                if json_match:
                    return json.loads(json_match.group(0))
                    
            except Exception as e:
                logger.error("json_extraction_failed", 
                           error=str(e),
                           response_preview=response_text[:500])
        
        logger.error("json_parse_failed", response_preview=response_text[:500])
        return None
