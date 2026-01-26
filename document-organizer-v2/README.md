# Document Organizer v2

A Docker-based document organization system that uses AI to detect duplicates, manage versions, and intelligently organize files.

## Features

- **Admin Configuration Panel**: Web-based UI for managing API credentials and settings
- **PowerAutomate Integration**: Flows for SharePoint configuration and authentication
- **Cloud Integration**: Download folders from OneDrive/SharePoint as ZIP
- **AI-Powered Analysis**: Uses local LLM (Ollama) and Claude API for content understanding
- **Duplicate Detection**: Content hashing + LLM decision-making for intelligent deduplication
- **Version Management**: Identifies document versions and applies version control
- **Smart Organization**: AI-driven file naming and categorization
- **Full Rollback**: All changes tracked with complete rollback capability
- **Large File Support**: Handles files >4MB with chunked upload sessions
- **Secure Configuration**: Encrypted credential storage with masked display

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Anthropic API key (for Claude)
- Python 3.11+ (for local development)

### 1. Clone and Configure

```bash
cd document-organizer-v2
cp .env.example .env
```

Edit `.env` and set required values:
- `ANTHROPIC_API_KEY` - Your Claude API key
- `POSTGRES_PASSWORD` - Database password (change from default)

### 2. Start Services

```bash
docker-compose up -d
```

### 3. Pull Ollama Model

```bash
docker exec -it doc_organizer_ollama ollama pull llama3.2
```

### 4. Configure via Admin Interface

Open your browser to `http://localhost:8000/admin` and:

1. **Configure Microsoft Graph API** (for SharePoint access)
   - Enter Tenant ID, Client ID, Client Secret
2. **Configure Ollama** (local LLM)
   - Verify URL: `http://ollama:11434`
3. **Configure Claude API** (optional but recommended)
   - Enter your Anthropic API key
4. **Test Connections**
   - Click "Test Connections" to verify all services

### 5. Process Documents

```bash
# Wait mode (watches for new ZIPs)
docker-compose exec processor python -m src.main --wait

# Or process a specific ZIP
docker-compose exec processor python -m src.main --zip /data/input/documents.zip

# Or trigger via API
curl -X POST http://localhost:8000/webhook/job \
  -H "Content-Type: application/json" \
  -d '{"source_path": "/data/input/documents.zip"}'
```

## Development Setup

For local development without Docker containers for the Python application:

### 1. Create Virtual Environment

```bash
cd document-organizer-v2
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start Required Services

The application still requires PostgreSQL and Ollama. Start them with Docker:

```bash
# Start only database and Ollama
docker-compose up -d postgres ollama

# Pull the Ollama model
docker exec -it doc_organizer_ollama ollama pull llama3.2
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Update `.env` for local development:
```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
OLLAMA_HOST=http://localhost:11434
ANTHROPIC_API_KEY=your-api-key-here
```

### 5. Run Application

```bash
# Run in wait mode
python -m src.main --wait

# Or process a specific ZIP
python -m src.main --zip ./data/input/documents.zip

# Run tests
python -m pytest tests/
```

### 6. Debug Database (Optional)

Access the database UI:
```bash
docker-compose --profile debug up -d adminer
```
Then open http://localhost:8080

## Production Deployment

### Full Docker Deployment

```bash
# Build and start all services
docker-compose up -d --build

# View logs
docker-compose logs -f processor

# Check service health
docker-compose ps
```

### With n8n Cloud Integration

For OneDrive/SharePoint integration, configure n8n workflows. See [n8n/README.md](n8n/README.md) for setup instructions.

Required additional environment variables:
```env
MS_TENANT_ID=your-azure-tenant-id
MS_CLIENT_ID=your-azure-client-id
MS_CLIENT_SECRET=your-azure-client-secret
```

### GPU Support (Optional)

For faster Ollama processing, enable GPU in `docker-compose.yml`:

```yaml
ollama:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

## Architecture

```
Index Agent → Dedup Agent → Version Agent → Organize Agent → Execution Engine
```

| Agent | Purpose |
|-------|---------|
| Index | File discovery, content hashing, metadata extraction |
| Dedup | Duplicate detection with LLM-powered decisions |
| Version | Version pattern detection and chain building |
| Organize | Claude AI-powered organization planning |
| Execution | Apply changes, create shortcuts, generate manifests |

## Data Volumes

| Path | Purpose |
|------|---------|
| `/data/input` | Downloaded ZIP files |
| `/data/source` | Extracted original files (never modified) |
| `/data/working` | Reorganized file structure |
| `/data/output` | Final ZIP for upload |
| `/data/reports` | Processing manifests and logs |

## Configuration

Key environment variables (see `.env.example` for full list):

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `POSTGRES_PASSWORD` | Yes | Database password |
| `OLLAMA_MODEL` | No | Ollama model (default: llama3.2) |
| `REVIEW_REQUIRED` | No | Require manual approval (default: true) |
| `DRY_RUN` | No | Simulate without changes (default: false) |

## Documentation

| Document | Description |
|----------|-------------|
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | Implementation status and file structure |
| [ORGANIZE_AGENT_README.md](ORGANIZE_AGENT_README.md) | Organization Agent details |
| [src/execution/README.md](src/execution/README.md) | Execution Engine documentation |
| [n8n/README.md](n8n/README.md) | Cloud integration workflows |
| [docs/](docs/) | Agent specifications |

## Troubleshooting

### Database Connection Failed
```bash
# Check if PostgreSQL is running
docker-compose ps postgres

# View database logs
docker-compose logs postgres
```

### Ollama Not Responding
```bash
# Check Ollama health
curl http://localhost:11434/api/tags

# View Ollama logs
docker-compose logs ollama
```

### Claude API Errors
- Verify `ANTHROPIC_API_KEY` is set correctly
- Check API quota at https://console.anthropic.com/

## License

MIT License - See LICENSE file for details.
