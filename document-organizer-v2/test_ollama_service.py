"""
Basic validation tests for OllamaService.

Tests key functionality without requiring an actual Ollama server.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_service_initialization():
    """Test OllamaService initialization."""
    print("Testing OllamaService initialization...")
    
    from src.services.ollama_service import OllamaService
    
    class MockSettings:
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3.2"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    service = OllamaService(MockSettings())
    
    assert service.base_url == "http://localhost:11434", "Base URL should match settings"
    print("  ✓ Base URL initialized correctly")
    
    assert service.model == "llama3.2", "Model should match settings"
    print("  ✓ Model initialized correctly")
    
    assert service.timeout == 120, "Timeout should match settings"
    print("  ✓ Timeout initialized correctly")
    
    assert service.temperature == 0.3, "Temperature should match settings"
    print("  ✓ Temperature initialized correctly")
    
    print("✓ OllamaService initialization tests passed")


def test_health_check_success():
    """Test health check with successful response."""
    print("\nTesting health_check success...")
    
    from src.services.ollama_service import OllamaService
    
    class MockSettings:
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3.2"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    service = OllamaService(MockSettings())
    
    # Mock successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {"name": "llama3.2:latest"},
            {"name": "mistral:latest"}
        ]
    }
    
    async def run_test():
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await service.health_check()
            return result
    
    result = asyncio.run(run_test())
    
    assert result is True, "Health check should pass with valid response"
    print("  ✓ Health check returns True on success")
    print("✓ Health check success tests passed")


def test_health_check_failure():
    """Test health check with failed connection."""
    print("\nTesting health_check failure...")
    
    from src.services.ollama_service import OllamaService
    import httpx
    
    class MockSettings:
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3.2"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    service = OllamaService(MockSettings())
    
    async def run_test():
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await service.health_check()
            return result
    
    result = asyncio.run(run_test())
    
    assert result is False, "Health check should fail with connection error"
    print("  ✓ Health check returns False on connection error")
    print("✓ Health check failure tests passed")


def test_generate_success():
    """Test generate with successful response."""
    print("\nTesting generate success...")
    
    from src.services.ollama_service import OllamaService
    
    class MockSettings:
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3.2"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    service = OllamaService(MockSettings())
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": "This is a test response from Ollama."
    }
    
    async def run_test():
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await service.generate("Test prompt")
            return result
    
    result = asyncio.run(run_test())
    
    assert result == "This is a test response from Ollama.", "Should return response text"
    print("  ✓ Generate returns response text on success")
    print("✓ Generate success tests passed")


def test_generate_with_system_prompt():
    """Test generate includes system prompt in payload."""
    print("\nTesting generate with system prompt...")
    
    from src.services.ollama_service import OllamaService
    
    class MockSettings:
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3.2"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    service = OllamaService(MockSettings())
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "Response"}
    
    captured_payload = None
    
    async def run_test():
        nonlocal captured_payload
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            
            async def capture_post(url, json):
                nonlocal captured_payload
                captured_payload = json
                return mock_response
            
            mock_instance.post = capture_post
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            await service.generate("Test prompt", system_prompt="You are a helpful assistant")
    
    asyncio.run(run_test())
    
    assert captured_payload is not None, "Should have captured payload"
    assert "system" in captured_payload, "Payload should include system prompt"
    assert captured_payload["system"] == "You are a helpful assistant"
    print("  ✓ System prompt is included in request payload")
    print("✓ Generate with system prompt tests passed")


def test_generate_retry_on_failure():
    """Test generate retries on transient failures."""
    print("\nTesting generate retry logic...")
    
    from src.services.ollama_service import OllamaService
    import httpx
    
    class MockSettings:
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3.2"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    service = OllamaService(MockSettings())
    
    call_count = 0
    
    mock_success_response = MagicMock()
    mock_success_response.status_code = 200
    mock_success_response.json.return_value = {"response": "Success after retry"}
    
    async def run_test():
        nonlocal call_count
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            
            async def mock_post(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 2:
                    raise httpx.TimeoutException("Timeout")
                return mock_success_response
            
            mock_instance.post = mock_post
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            # Reduce sleep time for test
            with patch('asyncio.sleep', new_callable=AsyncMock):
                result = await service.generate("Test prompt", max_retries=3)
                return result
    
    result = asyncio.run(run_test())
    
    assert call_count >= 2, f"Should have retried at least once, called {call_count} times"
    assert result == "Success after retry", "Should succeed after retry"
    print(f"  ✓ Retried {call_count} times before success")
    print("✓ Generate retry logic tests passed")


def test_chat_success():
    """Test chat with successful response."""
    print("\nTesting chat success...")
    
    from src.services.ollama_service import OllamaService
    
    class MockSettings:
        ollama_host = "http://localhost:11434"
        ollama_model = "llama3.2"
        ollama_timeout = 120
        ollama_temperature = 0.3
    
    service = OllamaService(MockSettings())
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "role": "assistant",
            "content": "Hello! How can I help you?"
        }
    }
    
    async def run_test():
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            messages = [{"role": "user", "content": "Hello"}]
            result = await service.chat(messages)
            return result
    
    result = asyncio.run(run_test())
    
    assert result == "Hello! How can I help you?", "Should return assistant content"
    print("  ✓ Chat returns assistant response on success")
    print("✓ Chat success tests passed")


def test_model_base_name_extraction():
    """Test that model base name is correctly extracted for matching."""
    print("\nTesting model base name extraction...")
    
    # Models can be specified with or without tags
    test_cases = [
        ("llama3.2", "llama3.2"),      # No tag
        ("llama3.2:latest", "llama3.2"),  # With tag
        ("mistral:7b", "mistral"),      # With version tag
    ]
    
    for full_name, expected_base in test_cases:
        model_base = full_name.split(':')[0] if ':' in full_name else full_name
        print(f"  {full_name} -> {model_base}")
        assert model_base == expected_base, f"Expected {expected_base}, got {model_base}"
    
    print("  ✓ Model base name extraction works correctly")
    print("✓ Model base name extraction tests passed")


def main():
    """Run all tests."""
    print("=" * 60)
    print("OllamaService Validation Tests")
    print("=" * 60)
    
    try:
        test_service_initialization()
        test_health_check_success()
        test_health_check_failure()
        test_generate_success()
        test_generate_with_system_prompt()
        test_generate_retry_on_failure()
        test_chat_success()
        test_model_base_name_extraction()
        
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
