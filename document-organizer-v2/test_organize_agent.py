"""
Basic tests for OrganizeAgent and ClaudeService.

These tests validate the core functionality without requiring actual API calls or database.
"""

from unittest.mock import patch
from src.agents.organize_agent import OrganizeAgent
from src.services.claude_service import ClaudeService
from src.config import Settings


class TestClaudeService:
    """Test ClaudeService functionality."""
    
    def test_initialization(self):
        """Test ClaudeService initializes correctly."""
        settings = Settings()
        service = ClaudeService(settings)
        assert service.model == settings.claude_model
        assert service.max_tokens == settings.claude_max_tokens
        assert service.base_url == "https://api.anthropic.com/v1/messages"
    
    def test_json_extraction_from_code_block(self):
        """Test JSON extraction from markdown code blocks."""
        service = ClaudeService()
        
        # Test with json code block
        response_text = '```json\n{"key": "value"}\n```'
        import asyncio
        
        async def test_extract():
            # Mock the generate method
            with patch.object(service, 'generate', return_value=response_text):
                result = await service.generate_json("test")
                assert result == {"key": "value"}
        
        asyncio.run(test_extract())
    
    def test_json_extraction_from_plain_json(self):
        """Test JSON extraction from plain JSON response."""
        service = ClaudeService()
        
        response_text = '{"key": "value"}'
        import asyncio
        
        async def test_extract():
            with patch.object(service, 'generate', return_value=response_text):
                result = await service.generate_json("test")
                assert result == {"key": "value"}
        
        asyncio.run(test_extract())


class TestOrganizeAgent:
    """Test OrganizeAgent functionality."""
    
    def test_flatten_tag_taxonomy(self):
        """Test flattening of hierarchical tag taxonomy."""
        settings = Settings()
        agent = OrganizeAgent(settings=settings)
        
        taxonomy = {
            "projects": {
                "description": "Projects",
                "children": {
                    "alpha": {"description": "Alpha project"},
                    "beta": {"description": "Beta project"}
                }
            },
            "types": {
                "description": "Document types",
                "children": {
                    "reports": {}
                }
            }
        }
        
        tags = agent._flatten_tag_taxonomy(taxonomy)
        
        # Should contain parent and child tags
        assert "projects" in tags
        assert "projects-alpha" in tags
        assert "projects-beta" in tags
        assert "types" in tags
        assert "types-reports" in tags
    
    def test_count_tags(self):
        """Test counting tags in taxonomy."""
        settings = Settings()
        agent = OrganizeAgent(settings=settings)
        
        taxonomy = {
            "projects": {
                "children": {
                    "alpha": {},
                    "beta": {}
                }
            },
            "types": {}
        }
        
        count = agent._count_tags(taxonomy)
        assert count == 4  # projects, alpha, beta, types
    
    def test_build_organization_prompt(self):
        """Test prompt building."""
        settings = Settings()
        agent = OrganizeAgent(settings=settings)
        
        files = [
            {
                "id": 1,
                "current_name": "test.docx",
                "current_path": "/Documents/test.docx",
                "extension": "docx",
                "size_bytes": 1024,
                "document_type": "document",
                "content_summary": "Test document",
                "key_topics": ["test"]
            }
        ]
        
        current_structure = ["/Documents"]
        
        prompt = agent._build_organization_prompt(files, current_structure)
        
        # Validate prompt contains expected sections
        assert "FILE INVENTORY" in prompt
        assert "CURRENT DIRECTORY STRUCTURE" in prompt
        assert "FILE TYPE DISTRIBUTION" in prompt
        assert "CRITICAL RULES" in prompt
        assert "RESPONSE FORMAT" in prompt
        assert "test.docx" in prompt


if __name__ == "__main__":
    # Run basic tests without pytest
    print("Testing ClaudeService...")
    test_claude = TestClaudeService()
    test_claude.test_initialization()
    print("✓ ClaudeService initialization test passed")
    
    print("\nTesting OrganizeAgent...")
    test_agent = TestOrganizeAgent()
    test_agent.test_flatten_tag_taxonomy()
    print("✓ Tag taxonomy flattening test passed")
    
    test_agent.test_count_tags()
    print("✓ Tag counting test passed")
    
    test_agent.test_build_organization_prompt()
    print("✓ Prompt building test passed")
    
    print("\n✅ All basic tests passed!")
