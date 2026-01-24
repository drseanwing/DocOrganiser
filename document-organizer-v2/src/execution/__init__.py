"""
Execution package for Document Organizer v2.

Handles the execution of planned file operations:
- Directory creation
- File moving/renaming
- Shortcut creation for duplicates
- Version archive setup
- Manifest generation
"""

from src.execution.execution_engine import ExecutionEngine
from src.execution.shortcut_creator import ShortcutCreator
from src.execution.manifest_generator import ManifestGenerator

__all__ = [
    "ExecutionEngine",
    "ShortcutCreator",
    "ManifestGenerator",
]
