#!/usr/bin/env python3
"""
Example script demonstrating OrganizeAgent usage.

This script shows how to:
1. Initialize the OrganizeAgent
2. Run the organization process
3. Handle results and errors

Note: This is a demonstration. In production, the agent would be called
from the main processing pipeline after Index, Dedup, and Version agents.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.agents.organize_agent import OrganizeAgent
from src.config import get_settings


async def run_organize_agent_example():
    """Example of running the OrganizeAgent."""
    
    print("=" * 70)
    print("Organization Agent Example")
    print("=" * 70)
    print()
    
    # Get settings
    settings = get_settings()
    
    # Check if API key is configured
    if not settings.anthropic_api_key:
        print("⚠️  WARNING: ANTHROPIC_API_KEY not set in environment")
        print("   Set it in .env file or as environment variable")
        print("   Example: export ANTHROPIC_API_KEY='sk-ant-...'")
        print()
        print("   This example will fail without a valid API key.")
        print()
    
    # Initialize agent
    print("Initializing OrganizeAgent...")
    agent = OrganizeAgent(settings=settings, job_id="example-job-123")
    print("✓ Agent initialized")
    print()
    
    # Validate prerequisites
    print("Validating prerequisites...")
    valid, error = await agent.validate_prerequisites()
    
    if not valid:
        print(f"✗ Prerequisites failed: {error}")
        print()
        print("This example requires:")
        print("  1. PostgreSQL database running with schema initialized")
        print("  2. Files indexed by IndexAgent (status='processed')")
        print("  3. Valid Anthropic API key")
        print()
        return False
    
    print("✓ Prerequisites validated")
    print()
    
    # Run organization
    print("Running organization process...")
    print("This will:")
    print("  1. Gather processable files from database")
    print("  2. Build prompt for Claude")
    print("  3. Call Claude API")
    print("  4. Parse organization plan")
    print("  5. Store results in database")
    print()
    
    try:
        result = await agent.run()
        
        print()
        print("=" * 70)
        print("Results")
        print("=" * 70)
        print()
        
        if result.success:
            print("✓ Organization completed successfully!")
            print()
            print(f"Files processed: {result.processed_count}")
            print(f"Duration: {result.duration_seconds:.2f} seconds")
            print()
            
            if result.metadata:
                print("Details:")
                print(f"  - Naming schemas created: {result.metadata.get('naming_schemas_created', 0)}")
                print(f"  - Tags created: {result.metadata.get('tags_created', 0)}")
                print(f"  - Directories planned: {result.metadata.get('directories_planned', 0)}")
                print(f"  - Files with changes: {result.metadata.get('files_with_changes', 0)}")
                print(f"  - Files unchanged: {result.metadata.get('files_unchanged', 0)}")
                print(f"  - Batch ID: {result.metadata.get('batch_id', 'N/A')}")
                
                if result.metadata.get('errors'):
                    print()
                    print("⚠️  Errors encountered:")
                    for error in result.metadata['errors'][:5]:  # Show first 5
                        print(f"    - {error}")
            
            print()
            print("Next steps:")
            print("  1. Review the organization plan in the database")
            print("  2. Approve changes if review_required=true")
            print("  3. Run ExecutionEngine to apply changes")
            
            return True
            
        else:
            print("✗ Organization failed")
            print(f"Error: {result.error}")
            print()
            
            if result.metadata and result.metadata.get('errors'):
                print("Additional errors:")
                for error in result.metadata['errors'][:5]:
                    print(f"  - {error}")
            
            return False
            
    except Exception as e:
        print()
        print(f"✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Cleanup
        await agent.cleanup()


def main():
    """Main entry point."""
    
    print()
    print("This example demonstrates the OrganizeAgent in action.")
    print()
    print("Prerequisites:")
    print("  - PostgreSQL database with document_organizer schema")
    print("  - Files indexed by IndexAgent")
    print("  - ANTHROPIC_API_KEY environment variable set")
    print()
    
    input("Press Enter to continue...")
    print()
    
    # Run async example
    success = asyncio.run(run_organize_agent_example())
    
    print()
    print("=" * 70)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
