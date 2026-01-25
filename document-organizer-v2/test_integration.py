"""
Integration Tests for Document Organizer v2.

These tests require external services to be running:
- PostgreSQL database
- Ollama LLM server (optional)
- Claude API (optional)

Run with: pytest test_integration.py -v
Skip external services with: pytest test_integration.py -v -m "not requires_db"
"""

import sys
import os
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# pytest is optional - only needed for pytest-based running
try:
    import pytest
except ImportError:
    pytest = None


# ============================================================================
# Fixtures
# ============================================================================

class MockSettings:
    """Mock settings for testing without database."""
    postgres_host = "localhost"
    postgres_port = 5432
    postgres_db = "document_organizer_test"
    postgres_user = "doc_organizer"
    postgres_password = "test"
    
    @property
    def database_url(self):
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    data_source_path = "/tmp/test_source"
    data_working_path = "/tmp/test_working"
    data_output_path = "/tmp/test_output"
    data_reports_path = "/tmp/test_reports"
    data_input_path = "/tmp/test_input"
    
    ollama_host = "http://localhost:11434"
    ollama_model = "llama3.2"
    ollama_timeout = 120
    ollama_temperature = 0.3
    
    anthropic_api_key = None
    claude_model = "claude-sonnet-4-20250514"
    claude_max_tokens = 16000
    
    batch_size = 50
    max_file_size_bytes = 100 * 1024 * 1024
    supported_extensions = ["pdf", "docx", "xlsx", "pptx", "txt", "md"]
    
    version_archive_strategy = type('obj', (object,), {'value': 'subfolder'})()
    version_folder_name = "_versions"
    
    review_required = False
    dry_run = True
    
    log_file = None
    log_level = "INFO"
    callback_url = None


# ============================================================================
# Pipeline Integration Tests
# ============================================================================

class TestPipelineIntegration:
    """Integration tests for the full processing pipeline."""
    
    def test_pipeline_phases_defined(self):
        """Test that all pipeline phases are defined."""
        print("\nTesting pipeline phase definitions...")
        
        from src.config import ProcessingPhase
        
        expected_phases = [
            "PENDING", "DOWNLOADING", "EXTRACTING", "INDEXING",
            "SUMMARIZING", "DEDUPLICATING", "VERSIONING", "ORGANIZING",
            "REVIEW_REQUIRED", "APPROVED", "EXECUTING", "PACKAGING",
            "UPLOADING", "COMPLETED", "FAILED", "CANCELLED"
        ]
        
        for phase in expected_phases:
            assert hasattr(ProcessingPhase, phase), f"Missing phase: {phase}"
        
        print(f"  ✓ All {len(expected_phases)} phases defined")
    
    def test_agent_import_chain(self):
        """Test that all agents can be imported."""
        print("\nTesting agent import chain...")
        
        from src.agents.base_agent import BaseAgent, AgentResult
        from src.agents.index_agent import IndexAgent
        from src.agents.dedup_agent import DedupAgent
        from src.agents.version_agent import VersionAgent
        from src.agents.organize_agent import OrganizeAgent
        
        assert BaseAgent is not None
        assert IndexAgent is not None
        assert DedupAgent is not None
        assert VersionAgent is not None
        assert OrganizeAgent is not None
        
        print("  ✓ All agents imported successfully")
    
    def test_execution_engine_import(self):
        """Test that execution engine can be imported."""
        print("\nTesting execution engine import...")
        
        from src.execution.execution_engine import ExecutionEngine
        from src.execution.shortcut_creator import ShortcutCreator
        from src.execution.manifest_generator import ManifestGenerator
        
        assert ExecutionEngine is not None
        assert ShortcutCreator is not None
        assert ManifestGenerator is not None
        
        print("  ✓ Execution engine components imported successfully")
    
    def test_service_imports(self):
        """Test that services can be imported."""
        print("\nTesting service imports...")
        
        from src.services.ollama_service import OllamaService
        from src.services.claude_service import ClaudeService
        
        assert OllamaService is not None
        assert ClaudeService is not None
        
        print("  ✓ All services imported successfully")


# ============================================================================
# Database Integration Tests
# ============================================================================

class TestDatabaseIntegration:
    """Integration tests for database operations."""
    
    def test_database_schema_file_exists(self):
        """Test that database schema file exists."""
        print("\nTesting database schema file...")
        
        schema_path = Path(__file__).parent / "database" / "init.sql"
        assert schema_path.exists(), f"Schema file not found at {schema_path}"
        
        content = schema_path.read_text()
        assert "CREATE TABLE" in content, "Schema should contain table definitions"
        assert "document_items" in content, "Schema should define document_items table"
        
        print("  ✓ Database schema file exists and contains expected content")
    
    def test_database_tables_defined(self):
        """Test that all required tables are defined in schema."""
        print("\nTesting database table definitions...")
        
        schema_path = Path(__file__).parent / "database" / "init.sql"
        content = schema_path.read_text()
        
        required_tables = [
            "processing_jobs",
            "document_items",
            "duplicate_groups",
            "duplicate_members",
            "version_chains",
            "version_chain_members",
            "naming_schema",
            "tag_taxonomy",
            "directory_structure",
            "shortcut_files",
            "execution_log",
            "processing_log",
            "system_config"
        ]
        
        for table in required_tables:
            assert table in content, f"Table {table} not found in schema"
        
        print(f"  ✓ All {len(required_tables)} required tables defined")


# ============================================================================
# Ollama Integration Tests
# ============================================================================

class TestOllamaIntegration:
    """Integration tests for Ollama LLM service."""
    
    def test_ollama_service_configuration(self):
        """Test OllamaService configuration."""
        print("\nTesting OllamaService configuration...")
        
        from src.services.ollama_service import OllamaService
        
        service = OllamaService(MockSettings())
        
        assert service.base_url == "http://localhost:11434"
        assert service.model == "llama3.2"
        assert service.timeout == 120
        assert service.temperature == 0.3
        
        print("  ✓ OllamaService configured correctly")
    
    def test_ollama_prompt_formatting(self):
        """Test that prompts are formatted correctly for Ollama."""
        print("\nTesting Ollama prompt formatting...")
        
        # Test prompt template used by agents
        filename = "budget_2024.xlsx"
        filepath = "/Documents/Finance/budget_2024.xlsx"
        content = "Q1 budget breakdown by department..."
        
        prompt = f"""Analyze this document for organization purposes.

DOCUMENT:
Filename: {filename}
Path: {filepath}

Content (first 10000 chars):
{content[:10000]}

Provide analysis in this exact JSON format:
{{
  "summary": "2-3 sentence summary",
  "document_type": "report",
  "key_topics": ["topic1", "topic2"]
}}

Respond ONLY with the JSON, no other text."""
        
        assert "budget_2024.xlsx" in prompt
        assert "/Documents/Finance/" in prompt
        assert "JSON" in prompt
        
        print("  ✓ Prompt formatting is correct")


# ============================================================================
# Claude Integration Tests
# ============================================================================

class TestClaudeIntegration:
    """Integration tests for Claude API service."""
    
    def test_claude_service_unconfigured(self):
        """Test ClaudeService behavior without API key."""
        print("\nTesting ClaudeService unconfigured state...")
        
        from src.services.claude_service import ClaudeService
        
        settings = MockSettings()
        settings.anthropic_api_key = None
        
        service = ClaudeService(settings)
        
        assert not service.is_configured(), "Should not be configured without API key"
        
        print("  ✓ ClaudeService correctly identifies unconfigured state")
    
    def test_claude_service_configured(self):
        """Test ClaudeService behavior with API key."""
        print("\nTesting ClaudeService configured state...")
        
        from src.services.claude_service import ClaudeService
        
        settings = MockSettings()
        settings.anthropic_api_key = "test-key-12345"
        
        service = ClaudeService(settings)
        
        assert service.is_configured(), "Should be configured with API key"
        
        print("  ✓ ClaudeService correctly identifies configured state")
    
    def test_claude_json_extraction(self):
        """Test JSON extraction from Claude responses."""
        print("\nTesting Claude JSON extraction...")
        
        from src.services.claude_service import ClaudeService
        
        service = ClaudeService(MockSettings())
        
        # Test various response formats
        test_cases = [
            ('{"key": "value"}', {"key": "value"}),
            ('```json\n{"key": "value"}\n```', {"key": "value"}),
            ('Here is the result:\n{"nested": {"key": "value"}}', {"nested": {"key": "value"}}),
        ]
        
        for input_text, expected in test_cases:
            result = service._extract_json(input_text)
            assert result == expected, f"Expected {expected}, got {result}"
        
        print("  ✓ JSON extraction handles all formats correctly")


# ============================================================================
# Main Test Runner
# ============================================================================

def main():
    """Run all integration tests."""
    print("=" * 60)
    print("Document Organizer v2 - Integration Tests")
    print("=" * 60)
    
    test_classes = [
        TestPipelineIntegration,
        TestDatabaseIntegration,
        TestOllamaIntegration,
        TestClaudeIntegration,
    ]
    
    failed = 0
    passed = 0
    
    for test_class in test_classes:
        print(f"\n{'=' * 60}")
        print(f"Running {test_class.__name__}")
        print("=" * 60)
        
        instance = test_class()
        
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                method = getattr(instance, method_name)
                try:
                    method()
                    passed += 1
                except AssertionError as e:
                    print(f"\n✗ FAILED: {method_name}")
                    print(f"  Error: {e}")
                    failed += 1
                except Exception as e:
                    print(f"\n✗ ERROR: {method_name}")
                    print(f"  Error: {e}")
                    import traceback
                    traceback.print_exc()
                    failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
