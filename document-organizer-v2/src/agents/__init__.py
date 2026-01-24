"""
Agents module for Document Organizer v2.

Exports all processing agents:
- IndexAgent: File discovery and content hashing
- DedupAgent: Duplicate detection and grouping
- VersionAgent: Version detection and chain building
- OrganizeAgent: AI-powered organization planning
"""

from src.agents.base_agent import BaseAgent, AgentResult
from src.agents.index_agent import IndexAgent
from src.agents.dedup_agent import DedupAgent
from src.agents.version_agent import VersionAgent
from src.agents.organize_agent import OrganizeAgent

__all__ = [
    "BaseAgent",
    "AgentResult",
    "IndexAgent",
    "DedupAgent",
    "VersionAgent",
    "OrganizeAgent",
]
