"""
Ollama Service - Local LLM API wrapper.

Provides async interface to Ollama for:
- Content summarization
- Decision making (duplicates, versions)
- Document classification
"""

import asyncio
import httpx
from typing import Optional

from src.config import Settings, get_settings
import structlog

logger = structlog.get_logger("ollama_service")


class OllamaService:
    """
    Async wrapper for Ollama API.
    
    Handles:
    - Connection management
    - Retries with backoff
    - Response parsing
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.ollama_host
        self.model = self.settings.ollama_model
        self.timeout = self.settings.ollama_timeout
        self.temperature = self.settings.ollama_temperature
    
    async def health_check(self) -> bool:
        """Check if Ollama is accessible and model is available."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m["name"] for m in data.get("models", [])]
                    # Check if our model is available (with or without tag)
                    model_base = self.model.split(':')[0] if ':' in self.model else self.model
                    model_available = any(
                        self.model in m or m.startswith(model_base)
                        for m in models
                    )
                    if not model_available:
                        logger.warning("model_not_found", 
                                      model=self.model, 
                                      available=models)
                    return True
                return False
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return False
    
    async def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Generate a response from Ollama.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt for context
            max_retries: Number of retries on failure
            
        Returns:
            Generated text or None on failure
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": 2000
            }
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/api/generate",
                        json=payload
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        return data.get("response", "")
                    
                    logger.warning("ollama_error_response", 
                                  status=response.status_code,
                                  attempt=attempt + 1)
                    
            except httpx.TimeoutException:
                logger.warning("ollama_timeout", attempt=attempt + 1)
            except Exception as e:
                logger.error("ollama_error", error=str(e), attempt=attempt + 1)
            
            # Exponential backoff
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        
        return None
    
    async def chat(
        self,
        messages: list[dict],
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Chat completion with message history.
        
        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            max_retries: Number of retries
            
        Returns:
            Assistant response or None
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature
            }
        }
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/api/chat",
                        json=payload
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        return data.get("message", {}).get("content", "")
                    
            except Exception as e:
                logger.error("ollama_chat_error", error=str(e))
            
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        
        return None
    
    async def pull_model(self) -> bool:
        """Pull the configured model if not already available."""
        try:
            # Model downloads can be large (1-4 GB); allow up to 15 minutes.
            async with httpx.AsyncClient(timeout=900) as client:
                response = await client.post(
                    f"{self.base_url}/api/pull",
                    json={"name": self.model, "stream": False}
                )
                return response.status_code == 200
        except Exception as e:
            logger.error("model_pull_failed", error=str(e), model=self.model)
            return False
