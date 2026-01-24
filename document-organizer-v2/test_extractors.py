"""
Basic validation tests for Document Extractors.

Tests key functionality without requiring external dependencies.
"""

import sys
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_extractor_registry():
    """Test that extractor registry has expected entries."""
    print("Testing extractor registry...")
    
    from src.extractors import EXTRACTORS, get_extractor, is_supported
    
    # Check that supported extensions are registered
    expected_extensions = ['txt', 'md', 'pdf', 'docx', 'xlsx', 'pptx']
    
    for ext in expected_extensions:
        assert ext in EXTRACTORS, f"Extension {ext} should be in registry"
        extractor = get_extractor(ext)
        assert extractor is not None, f"Should get extractor for {ext}"
    
    print(f"  ✓ Registry contains {len(EXTRACTORS)} extensions")
    print("  ✓ All expected extensions are registered")
    print("✓ Extractor registry tests passed")


def test_is_supported():
    """Test is_supported function."""
    print("\nTesting is_supported function...")
    
    from src.extractors import is_supported
    
    # Supported
    assert is_supported("txt") is True, "txt should be supported"
    assert is_supported("pdf") is True, "pdf should be supported"
    assert is_supported("docx") is True, "docx should be supported"
    
    # Not supported
    assert is_supported("exe") is False, "exe should not be supported"
    assert is_supported("mp4") is False, "mp4 should not be supported"
    assert is_supported("unknown") is False, "unknown should not be supported"
    
    # Case insensitive
    assert is_supported("TXT") is True, "TXT (uppercase) should be supported"
    assert is_supported("PDF") is True, "PDF (uppercase) should be supported"
    
    print("  ✓ is_supported correctly identifies supported extensions")
    print("  ✓ is_supported correctly rejects unsupported extensions")
    print("  ✓ is_supported is case insensitive")
    print("✓ is_supported tests passed")


def test_text_extractor():
    """Test TextExtractor with plain text files."""
    print("\nTesting TextExtractor...")
    
    from src.extractors import TextExtractor
    
    extractor = TextExtractor()
    
    # Create a temp text file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as f:
        f.write("Hello, World!\nThis is a test file.")
        temp_path = f.name
    
    try:
        async def run_extract():
            return await extractor.extract(Path(temp_path))
        
        result = asyncio.run(run_extract())
        
        assert result is not None, "Should extract text"
        assert "Hello, World!" in result, "Should contain expected text"
        assert "This is a test file" in result, "Should contain all content"
        
        print("  ✓ TextExtractor extracts plain text correctly")
        
    finally:
        os.unlink(temp_path)
    
    print("✓ TextExtractor tests passed")


def test_text_extractor_encoding():
    """Test TextExtractor with different encodings."""
    print("\nTesting TextExtractor encoding handling...")
    
    from src.extractors import TextExtractor
    
    extractor = TextExtractor()
    
    # Create a file with UTF-8 content
    with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.txt') as f:
        f.write("Héllo Wörld! 你好".encode('utf-8'))
        temp_path = f.name
    
    try:
        async def run_extract():
            return await extractor.extract(Path(temp_path))
        
        result = asyncio.run(run_extract())
        
        assert result is not None, "Should extract UTF-8 text"
        assert "Héllo" in result, "Should handle accented characters"
        assert "你好" in result, "Should handle CJK characters"
        
        print("  ✓ TextExtractor handles UTF-8 encoding")
        
    finally:
        os.unlink(temp_path)
    
    print("✓ TextExtractor encoding tests passed")


def test_base_extractor_interface():
    """Test that all extractors implement the BaseExtractor interface."""
    print("\nTesting BaseExtractor interface...")
    
    from src.extractors import BaseExtractor, EXTRACTORS
    
    for ext, extractor in EXTRACTORS.items():
        assert isinstance(extractor, BaseExtractor), f"Extractor for {ext} should inherit BaseExtractor"
        assert hasattr(extractor, 'extract'), f"Extractor for {ext} should have extract method"
        assert asyncio.iscoroutinefunction(extractor.extract), f"Extractor for {ext}.extract should be async"
    
    print(f"  ✓ All {len(EXTRACTORS)} extractors implement BaseExtractor")
    print("✓ BaseExtractor interface tests passed")


def test_pdf_extractor_fallback():
    """Test PDFExtractor fallback mechanism."""
    print("\nTesting PDFExtractor fallback...")
    
    from src.extractors import PDFExtractor
    
    extractor = PDFExtractor()
    
    # Test that _fallback_pdftotext method exists
    assert hasattr(extractor, '_fallback_pdftotext'), "Should have fallback method"
    
    print("  ✓ PDFExtractor has fallback mechanism")
    print("✓ PDFExtractor fallback tests passed")


def test_docx_extractor_fallback():
    """Test DocxExtractor fallback mechanism."""
    print("\nTesting DocxExtractor fallback...")
    
    from src.extractors import DocxExtractor
    
    extractor = DocxExtractor()
    
    # Test that _fallback_pandoc method exists
    assert hasattr(extractor, '_fallback_pandoc'), "Should have fallback method"
    
    print("  ✓ DocxExtractor has fallback mechanism")
    print("✓ DocxExtractor fallback tests passed")


def test_get_extractor_returns_none_for_unsupported():
    """Test that get_extractor returns None for unsupported extensions."""
    print("\nTesting get_extractor with unsupported extensions...")
    
    from src.extractors import get_extractor
    
    unsupported = ['exe', 'dll', 'so', 'bin', 'mp4', 'avi', 'jpg', 'png']
    
    for ext in unsupported:
        extractor = get_extractor(ext)
        assert extractor is None, f"Should return None for {ext}"
    
    print(f"  ✓ Returns None for {len(unsupported)} unsupported extensions")
    print("✓ get_extractor unsupported extension tests passed")


def test_extractor_error_handling():
    """Test that extractors handle errors gracefully."""
    print("\nTesting extractor error handling...")
    
    from src.extractors import TextExtractor
    
    extractor = TextExtractor()
    
    async def run_extract():
        # Try to extract from a non-existent file
        try:
            result = await extractor.extract(Path("/nonexistent/file.txt"))
            # Should return None, not raise exception
            return result
        except Exception:
            return "EXCEPTION"
    
    result = asyncio.run(run_extract())
    
    # Extractor should either return None or handle exception gracefully
    assert result is None, "Should return None for missing file"
    
    print("  ✓ Extractors handle errors gracefully")
    print("✓ Extractor error handling tests passed")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Document Extractors Validation Tests")
    print("=" * 60)
    
    try:
        test_extractor_registry()
        test_is_supported()
        test_text_extractor()
        test_text_extractor_encoding()
        test_base_extractor_interface()
        test_pdf_extractor_fallback()
        test_docx_extractor_fallback()
        test_get_extractor_returns_none_for_unsupported()
        test_extractor_error_handling()
        
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
