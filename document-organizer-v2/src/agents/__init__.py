"""
Document Organizer Agents.

Available agents:
- IndexAgent: File discovery and content hashing
- DedupAgent: Duplicate detection and grouping
- OrganizeAgent: AI-powered organization planning
"""

from src.agents.base_agent import BaseAgent, AgentResult
from src.agents.index_agent import IndexAgent
from src.agents.dedup_agent import DedupAgent
from src.agents.organize_agent import OrganizeAgent

__all__ = [
    "BaseAgent",
    "AgentResult",
    "IndexAgent",
    "DedupAgent",
    "OrganizeAgent"
]
