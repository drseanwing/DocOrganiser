# DocOrganiser

An AI-powered document organization system that autonomously renames, categorizes, and reorganizes bulky file system directories.

## Overview

DocOrganiser uses a multi-agent architecture to process documents from OneDrive/SharePoint, leveraging local LLM inference (Ollama) and cloud LLMs (Claude) to make intelligent decisions about document organization.

## Key Features

- **Duplicate Detection**: Identifies and manages duplicate files across directories
- **Version Control**: Detects document versions and establishes version chains
- **AI-Powered Organization**: Uses LLMs to propose intelligent naming and categorization
- **Rollback Support**: All changes are tracked with full rollback capability
- **Cloud Integration**: Works with OneDrive and SharePoint via Microsoft Graph API

## Architecture

```
┌─────────────┐     ┌─────────────────────────────────────────────────────┐
│ OneDrive/   │────▶│                 DOCKER CONTAINER                    │
│ SharePoint  │     │                                                     │
│             │     │  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────────┐        │
│             │     │  │Index │─▶│Dedup │─▶│Version│─▶│Organize  │        │
│             │     │  │Agent │  │Agent │  │Agent  │  │Agent     │        │
│             │     │  └──────┘  └──────┘  └──────┘  └──────────┘        │
│             │     │      │          │         │          │              │
│             │     │      ▼          ▼         ▼          ▼              │
│             │◀────│  ┌──────────────────────────────────────┐          │
│             │     │  │         PostgreSQL Database          │          │
└─────────────┘     │  └──────────────────────────────────────┘          │
                    └─────────────────────────────────────────────────────┘
```

## Quick Start

```bash
cd document-organizer-v2

# Start services with Docker
docker-compose up -d

# Process a ZIP file
python -m src.main --zip /data/input/documents.zip
```

## Documentation

All documentation is located in the `document-organizer-v2/` directory:

- **[README.md](document-organizer-v2/README.md)** - Architecture and design
- **[IMPLEMENTATION_STATUS.md](document-organizer-v2/IMPLEMENTATION_STATUS.md)** - Implementation status
- **[ORGANIZE_AGENT_README.md](document-organizer-v2/ORGANIZE_AGENT_README.md)** - Organization agent details
- **[n8n/README.md](document-organizer-v2/n8n/README.md)** - Cloud workflow integration
- **[src/execution/README.md](document-organizer-v2/src/execution/README.md)** - Execution engine

## Technology Stack

- **Python 3.11+** with async/await patterns
- **PostgreSQL** for metadata and decision tracking
- **Ollama** for local LLM inference
- **Claude (Anthropic)** for complex reasoning tasks
- **Docker Compose** for container orchestration
- **n8n** for cloud workflow automation

## Project Structure

```
DocOrganiser/
├── document-organizer-v2/       # Main application
│   ├── src/                     # Python source code
│   │   ├── agents/              # Processing agents
│   │   ├── services/            # LLM services
│   │   ├── execution/           # File operations
│   │   └── main.py              # Orchestrator
│   ├── database/                # SQL schema
│   ├── n8n/                     # Cloud workflows
│   └── docs/                    # Implementation specs
└── .github/                     # GitHub configuration
```

## License

See LICENSE file for details.
