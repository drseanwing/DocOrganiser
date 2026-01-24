# GitHub Copilot Instructions - DocOrganiser

## Project Overview

**DocOrganiser** is an AI-powered document organization system that autonomously renames, categorizes, and reorganizes bulky file system directories. The system uses a multi-agent architecture to process documents from OneDrive/SharePoint, leveraging local LLM inference (Ollama) and cloud LLMs (Claude, OpenAI) to make intelligent decisions about document organization.

### Core Capabilities

1. **Index Agent**: Discovers files and builds inventory with content hashing
2. **Duplicate Detection Agent**: Identifies duplicate files and determines handling strategy
3. **Version Control Agent**: Detects document versions and establishes version chains
4. **Organize Agent**: Proposes intelligent naming and categorization
5. **Execution Engine**: Applies changes with rollback capability

---

## Technology Stack

- **Language**: Python 3.9+
- **Async Framework**: asyncio, asyncpg
- **Database**: PostgreSQL 15+
- **LLM Inference**: 
  - Local: Ollama (llama3, mistral, etc.)
  - Cloud: Claude API (Anthropic), OpenAI API
- **File Access**: Microsoft Graph API (OneDrive/SharePoint)
- **Orchestration**: n8n (self-hosted workflows)
- **Container**: Docker Compose
- **Document Processing**: python-docx, PyMuPDF, openpyxl, python-pptx
- **HTTP Clients**: httpx, aiohttp (async)
- **Logging**: structlog
- **Testing**: pytest, pytest-asyncio

---

## Code Quality Standards

### 1. Production-Ready Code

- **No placeholders**: All code must be deployable, no TODOs without implementation
- **Complete logic**: No partial implementations or commented-out alternatives
- **Real error handling**: No pass or generic exceptions

### 2. Async/Await Patterns

All I/O operations must be asynchronous:

```python
# GOOD: Async database operations
async def get_document(doc_id: int) -> Optional[Document]:
    async with self.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM document_items WHERE id = $1",
            doc_id
        )
        return Document.from_row(row) if row else None

# GOOD: Async HTTP requests
async def query_ollama(prompt: str, model: str = "llama3") -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{self.ollama_base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False}
        )
        response.raise_for_status()
        return response.json()["response"]
```

### 3. Structured Logging

Use structlog for all logging with contextual data:

```python
import structlog

logger = structlog.get_logger("agent_name")

# GOOD: Structured logging with context
logger.info(
    "document_processed",
    doc_id=doc.id,
    file_path=doc.path,
    status="success",
    processing_time_ms=elapsed_ms
)

# GOOD: Error logging with traceback
logger.error(
    "processing_failed",
    doc_id=doc.id,
    error=str(e),
    error_type=type(e).__name__,
    traceback=traceback.format_exc()
)
```

### 4. Comprehensive Error Handling

Implement graceful degradation, never fail silently:

```python
async def process_document(self, doc: Document) -> ProcessingResult:
    """Process a document with comprehensive error handling."""
    try:
        # Attempt processing
        result = await self._analyze_content(doc)
        logger.info("document_processed", doc_id=doc.id, status="success")
        return ProcessingResult(status="success", data=result)
    
    except ValidationError as e:
        # Expected error - document doesn't meet criteria
        logger.warning("validation_failed", doc_id=doc.id, reason=str(e))
        return ProcessingResult(status="skipped", reason=str(e))
    
    except ExternalAPIError as e:
        # Retry logic for transient failures
        logger.warning("api_error", doc_id=doc.id, attempt=attempt, error=str(e))
        if attempt < max_retries:
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
            return await self.process_document(doc, attempt + 1)
        return ProcessingResult(status="error", error="API unavailable")
    
    except Exception as e:
        # Unexpected error - log and continue with other documents
        logger.error(
            "unexpected_error",
            doc_id=doc.id,
            error=str(e),
            traceback=traceback.format_exc()
        )
        return ProcessingResult(status="error", error=str(e))
```

### 5. Modular Architecture

Follow the agent-based architecture pattern:

```python
from abc import ABC, abstractmethod
from typing import Optional
import asyncpg
import structlog

class BaseAgent(ABC):
    """Base class for all processing agents."""
    
    def __init__(self, db_pool: asyncpg.Pool, config: Config):
        self.db = db_pool
        self.config = config
        self.logger = structlog.get_logger(self.__class__.__name__)
    
    @abstractmethod
    async def run(self) -> AgentResult:
        """Main processing logic - override in subclass."""
        pass
    
    async def update_progress(self, current: int, total: int, message: str):
        """Update progress in database for tracking."""
        async with self.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_progress (agent_name, current, total, message, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (agent_name) 
                DO UPDATE SET current = $2, total = $3, message = $4, updated_at = NOW()
                """,
                self.__class__.__name__, current, total, message
            )
```

---

## Naming Conventions

| Context | Convention | Example |
|---------|-----------|---------|
| Python Classes | PascalCase | `DocumentProcessor`, `IndexAgent` |
| Python Functions | snake_case | `process_document()`, `extract_text()` |
| Python Variables | snake_case | `doc_id`, `file_path`, `processing_status` |
| Python Constants | SCREAMING_SNAKE | `DEFAULT_TIMEOUT`, `MAX_BATCH_SIZE` |
| Database Tables | snake_case (plural) | `document_items`, `duplicate_groups` |
| Database Columns | snake_case | `content_hash`, `created_at`, `file_size_bytes` |
| API Endpoints | kebab-case | `/api/v1/document-items`, `/api/v1/organize-agent/run` |
| Environment Variables | SCREAMING_SNAKE | `OLLAMA_BASE_URL`, `POSTGRES_HOST` |
| Module Files | snake_case | `version_agent.py`, `graph_api_client.py` |

---

## Database Schema Conventions

All tables must include audit columns and use appropriate indexes:

```sql
-- Standard audit columns for all tables
created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
created_by TEXT,

-- Use JSONB for flexible metadata
metadata JSONB DEFAULT '{}'::jsonb,

-- Always add indexes for frequently queried columns
CREATE INDEX idx_document_items_status ON document_items(processing_status);
CREATE INDEX idx_document_items_hash ON document_items(content_hash);
CREATE INDEX idx_document_items_created ON document_items(created_at DESC);

-- Use partial indexes for common query patterns
CREATE INDEX idx_document_items_pending 
    ON document_items(created_at) 
    WHERE processing_status = 'pending';
```

### Key Database Tables

1. **document_items**: Main inventory of all discovered files
2. **duplicate_groups**: Tracks duplicate file relationships and handling decisions
3. **version_chains**: Stores version relationships between documents
4. **organization_proposals**: LLM-generated suggestions for file organization
5. **execution_log**: Tracks all filesystem operations for rollback

---

## Architecture Patterns

### Multi-Agent Pipeline

Agents run sequentially, each depending on previous agent's output:

```python
async def run_pipeline(db_pool: asyncpg.Pool, config: Config):
    """Execute the full document organization pipeline."""
    logger = structlog.get_logger("pipeline")
    
    # Agent 1: Index - Build inventory
    logger.info("starting_agent", agent="IndexAgent")
    index_agent = IndexAgent(db_pool, config)
    index_result = await index_agent.run()
    if not index_result.success:
        logger.error("agent_failed", agent="IndexAgent", error=index_result.error)
        return PipelineResult(success=False, failed_at="IndexAgent")
    
    # Agent 2: Duplicate Detection
    logger.info("starting_agent", agent="DuplicateDetectionAgent")
    dedup_agent = DuplicateDetectionAgent(db_pool, config)
    dedup_result = await dedup_agent.run()
    if not dedup_result.success:
        logger.error("agent_failed", agent="DuplicateDetectionAgent")
        return PipelineResult(success=False, failed_at="DuplicateDetectionAgent")
    
    # Agent 3: Version Control
    logger.info("starting_agent", agent="VersionControlAgent")
    version_agent = VersionControlAgent(db_pool, config)
    version_result = await version_agent.run()
    
    # Agent 4: Organization
    logger.info("starting_agent", agent="OrganizeAgent")
    organize_agent = OrganizeAgent(db_pool, config)
    organize_result = await organize_agent.run()
    
    # Agent 5: Execution (if not test mode)
    if not config.test_mode:
        logger.info("starting_agent", agent="ExecutionEngine")
        executor = ExecutionEngine(db_pool, config)
        exec_result = await executor.run()
        return PipelineResult(success=True, execution_summary=exec_result)
    
    return PipelineResult(success=True, test_mode=True)
```

### Batch Processing Pattern

Process large document sets in configurable batches:

```python
async def process_in_batches(
    self, 
    items: List[Document], 
    batch_size: int = 50
) -> List[ProcessingResult]:
    """Process items in batches with progress tracking."""
    results = []
    total = len(items)
    
    for i in range(0, total, batch_size):
        batch = items[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        
        self.logger.info(
            "processing_batch",
            batch_num=batch_num,
            total_batches=total_batches,
            batch_size=len(batch)
        )
        
        # Process batch concurrently
        batch_results = await asyncio.gather(
            *[self.process_document(doc) for doc in batch],
            return_exceptions=True
        )
        
        results.extend(batch_results)
        await self.update_progress(i + len(batch), total, f"Batch {batch_num}/{total_batches}")
    
    return results
```

### Retry Logic with Exponential Backoff

Implement retry logic for external API calls:

```python
async def call_with_retry(
    self,
    operation: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0
) -> Any:
    """Execute operation with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            return await operation()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            if attempt == max_retries - 1:
                self.logger.error(
                    "retry_exhausted",
                    operation=operation.__name__,
                    attempts=max_retries,
                    error=str(e)
                )
                raise
            
            delay = base_delay * (2 ** attempt)
            self.logger.warning(
                "retrying_operation",
                operation=operation.__name__,
                attempt=attempt + 1,
                delay_seconds=delay,
                error=str(e)
            )
            await asyncio.sleep(delay)
```

---

## LLM Integration Patterns

### Ollama (Local LLM)

Use for bulk operations (summaries, content analysis):

```python
async def query_ollama(
    self,
    prompt: str,
    model: str = "llama3",
    temperature: float = 0.1
) -> str:
    """Query local Ollama instance."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": 4096
        }
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{self.config.ollama_base_url}/api/generate",
            json=payload
        )
        response.raise_for_status()
        return response.json()["response"]
```

### Claude API (Complex Reasoning)

Use for complex decisions (organization, naming):

```python
async def query_claude(
    self,
    prompt: str,
    model: str = "claude-3-5-sonnet-20241022",
    max_tokens: int = 4096
) -> str:
    """Query Claude API for complex reasoning tasks."""
    headers = {
        "x-api-key": self.config.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]
```

### LLM Prompt Structure

Structure prompts for consistent, parseable output:

```python
def build_organization_prompt(self, doc: Document) -> str:
    """Build structured prompt for document organization."""
    return f"""You are a document organization assistant. Analyze this document and propose organization.

DOCUMENT INFO:
- Path: {doc.file_path}
- Name: {doc.file_name}
- Type: {doc.file_extension}
- Size: {doc.file_size_bytes} bytes
- Created: {doc.created_date}
- Modified: {doc.modified_date}

CONTENT SUMMARY:
{doc.content_summary[:500]}

TASK:
Propose a new name and category for this document following these rules:
1. Use descriptive, searchable names
2. Include date if relevant (YYYY-MM-DD format)
3. Use underscores, not spaces
4. Categories: Projects, Reports, Finance, Legal, HR, Marketing, Other

OUTPUT FORMAT (JSON):
{{
  "proposed_name": "descriptive_name_YYYY-MM-DD.ext",
  "category": "category_name",
  "confidence": "high|medium|low",
  "reasoning": "explanation for the proposal"
}}
"""
```

---

## Microsoft Graph API Integration

### Authentication

```python
import httpx
from typing import Optional

class GraphAPIClient:
    """Client for Microsoft Graph API operations."""
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: Optional[str] = None
        self.logger = structlog.get_logger("GraphAPIClient")
    
    async def get_access_token(self) -> str:
        """Obtain access token via client credentials flow."""
        if self.access_token:
            return self.access_token
        
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data["access_token"]
            self.logger.info("access_token_obtained", expires_in=token_data.get("expires_in"))
            return self.access_token
    
    async def list_drive_items(self, drive_id: str, folder_path: str = "root") -> List[dict]:
        """List items in a OneDrive folder."""
        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder_path}:/children"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()["value"]
```

---

## n8n Workflow Conventions

When working with n8n workflows:

1. **Environment Variables**: Always use `{{ $env.VAR_NAME }}` for configuration
2. **Credentials**: Store in n8n Credentials UI, never hardcoded
3. **Node Naming**: Use descriptive names like "Get Documents from Database" not "Postgres 1"
4. **Error Handling**: Add Error Trigger nodes for workflow failure notifications
5. **Code Nodes**: Use for complex transformations, return structured data
6. **HTTP Nodes**: Include timeout settings and retry logic

Example n8n Code Node:

```javascript
// Process document batch from previous node
const items = $input.all();
const processed = [];

for (const item of items) {
  const doc = item.json;
  
  // Transform data
  processed.push({
    json: {
      doc_id: doc.id,
      file_path: doc.file_path,
      processing_status: 'pending',
      created_at: new Date().toISOString()
    }
  });
}

return processed;
```

---

## Testing Standards

### Unit Tests

Use pytest with async support:

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_process_document_success():
    """Test successful document processing."""
    # Arrange
    mock_db = AsyncMock()
    config = Config(test_mode=True)
    agent = IndexAgent(mock_db, config)
    
    doc = Document(
        id=1,
        file_path="/test/document.pdf",
        file_name="document.pdf",
        file_size_bytes=1024
    )
    
    # Act
    result = await agent.process_document(doc)
    
    # Assert
    assert result.status == "success"
    assert result.data is not None
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_process_document_handles_api_error():
    """Test graceful handling of API errors."""
    # Arrange
    mock_db = AsyncMock()
    config = Config(test_mode=True)
    agent = IndexAgent(mock_db, config)
    
    # Mock API failure
    agent._call_external_api = AsyncMock(side_effect=httpx.RequestError("Connection failed"))
    
    doc = Document(id=1, file_path="/test/document.pdf")
    
    # Act
    result = await agent.process_document(doc)
    
    # Assert
    assert result.status == "error"
    assert "Connection failed" in result.error
```

### Integration Tests

Test full agent workflows:

```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_index_agent_full_workflow(test_db_pool, sample_documents):
    """Test IndexAgent processes multiple documents correctly."""
    # Arrange
    config = Config(test_mode=True, batch_size=10)
    agent = IndexAgent(test_db_pool, config)
    
    # Act
    result = await agent.run()
    
    # Assert
    assert result.success is True
    assert result.documents_processed == len(sample_documents)
    
    # Verify database state
    async with test_db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM document_items")
        assert count == len(sample_documents)
```

---

## Configuration Management

Use pydantic for type-safe configuration:

```python
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import Optional

class Config(BaseSettings):
    """Application configuration with environment variable support."""
    
    # Database
    postgres_host: str = Field(default="localhost", env="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, env="POSTGRES_PORT")
    postgres_db: str = Field(default="docorganiser", env="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", env="POSTGRES_USER")
    postgres_password: str = Field(env="POSTGRES_PASSWORD")
    
    # Ollama
    ollama_base_url: str = Field(default="http://localhost:11434", env="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3", env="OLLAMA_MODEL")
    
    # Claude API
    anthropic_api_key: Optional[str] = Field(default=None, env="ANTHROPIC_API_KEY")
    claude_model: str = Field(default="claude-3-5-sonnet-20241022", env="CLAUDE_MODEL")
    
    # Microsoft Graph
    azure_tenant_id: Optional[str] = Field(default=None, env="AZURE_TENANT_ID")
    azure_client_id: Optional[str] = Field(default=None, env="AZURE_CLIENT_ID")
    azure_client_secret: Optional[str] = Field(default=None, env="AZURE_CLIENT_SECRET")
    
    # Processing
    batch_size: int = Field(default=50, env="BATCH_SIZE")
    max_retries: int = Field(default=3, env="MAX_RETRIES")
    test_mode: bool = Field(default=True, env="TEST_MODE")
    
    # Paths
    data_dir: str = Field(default="/data", env="DATA_DIR")
    source_dir: str = Field(default="/data/source", env="SOURCE_DIR")
    working_dir: str = Field(default="/data/working", env="WORKING_DIR")
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Usage
config = Config()
```

---

## Docker Patterns

### Docker Compose Structure

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./database/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_models:/root/.ollama
    ports:
      - "11434:11434"

  processor:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      ollama:
        condition: service_started
    environment:
      POSTGRES_HOST: postgres
      OLLAMA_BASE_URL: http://ollama:11434
      TEST_MODE: ${TEST_MODE:-true}
    volumes:
      - ./data/source:/data/source
      - ./data/working:/data/working
      - ./data/output:/data/output

volumes:
  postgres_data:
  ollama_models:
```

---

## Security Considerations

1. **Never commit secrets**: Use environment variables for all credentials
2. **Validate all inputs**: Sanitize file paths, validate file types
3. **SQL injection prevention**: Always use parameterized queries
4. **File path traversal**: Validate paths are within expected directories
5. **Content scanning**: Check file types and sizes before processing
6. **API rate limiting**: Implement backoff and respect rate limits

```python
import os
from pathlib import Path

def validate_file_path(file_path: str, base_dir: str) -> bool:
    """Validate file path is within expected directory."""
    try:
        # Resolve to absolute path
        abs_path = Path(file_path).resolve()
        abs_base = Path(base_dir).resolve()
        
        # Check if path is within base directory
        return abs_path.is_relative_to(abs_base)
    except (ValueError, OSError):
        return False
```

---

## Common Patterns to Avoid

### ❌ DON'T: Use blocking I/O in async functions

```python
# BAD: Blocks the event loop
async def process_file(file_path: str):
    with open(file_path, 'r') as f:  # Blocking!
        content = f.read()
    return content
```

✅ **DO: Use async file I/O**

```python
# GOOD: Non-blocking async I/O
import aiofiles

async def process_file(file_path: str):
    async with aiofiles.open(file_path, 'r') as f:
        content = await f.read()
    return content
```

### ❌ DON'T: Ignore exceptions or use bare except

```python
# BAD: Silent failures
try:
    result = await process_document(doc)
except:
    pass
```

✅ **DO: Handle specific exceptions with logging**

```python
# GOOD: Explicit error handling
try:
    result = await process_document(doc)
except ValidationError as e:
    logger.warning("validation_failed", doc_id=doc.id, error=str(e))
    return ProcessingResult(status="skipped", reason=str(e))
except Exception as e:
    logger.error("processing_failed", doc_id=doc.id, error=str(e))
    raise
```

### ❌ DON'T: Use print() for logging

```python
# BAD: No structured data, hard to search
print(f"Processing document {doc_id}")
print(f"Error: {e}")
```

✅ **DO: Use structured logging**

```python
# GOOD: Structured, searchable logs
logger.info("document_processing_started", doc_id=doc_id, file_path=path)
logger.error("processing_error", doc_id=doc_id, error=str(e), error_type=type(e).__name__)
```

---

## Key Design Principles

1. **Async-First**: All I/O operations must be asynchronous
2. **Fail Gracefully**: Never let one document failure stop the entire pipeline
3. **Observable**: Log all operations with structured data for debugging
4. **Testable**: Design for dependency injection and mocking
5. **Recoverable**: Store all state in database for pipeline recovery
6. **Configurable**: Use environment variables for all configuration
7. **Type-Safe**: Use type hints and pydantic models throughout
8. **Batch Processing**: Process large datasets in configurable batches
9. **Idempotent**: Agents should be re-runnable without side effects
10. **Test Mode**: Always support dry-run mode for safe testing

---

## When Working on This Project

1. **Check existing agents**: Before creating new functionality, review existing agent implementations
2. **Follow the agent pattern**: New processing logic should inherit from `BaseAgent`
3. **Update database schema**: New features may require schema changes - add migrations
4. **Test with Ollama first**: Use local LLM for development, Cloud LLMs for production
5. **Log everything**: All operations should produce structured logs
6. **Handle edge cases**: Consider empty directories, corrupted files, missing metadata
7. **Document decisions**: LLM decisions should be stored in database with reasoning
8. **Support rollback**: All filesystem changes must be reversible

---

## Project Structure Reference

```
document-organizer-v2/
├── src/
│   ├── agents/           # Processing agents
│   │   ├── index_agent.py
│   │   ├── duplicate_detection_agent.py
│   │   ├── version_control_agent.py
│   │   └── organize_agent.py
│   ├── execution/        # Execution engine
│   │   ├── executor.py
│   │   └── rollback.py
│   ├── extractors/       # Document text extraction
│   │   ├── pdf_extractor.py
│   │   ├── docx_extractor.py
│   │   └── xlsx_extractor.py
│   ├── services/         # External service clients
│   │   ├── ollama_client.py
│   │   ├── claude_client.py
│   │   └── graph_api_client.py
│   ├── utils/           # Utility functions
│   │   ├── hashing.py
│   │   ├── file_utils.py
│   │   └── string_similarity.py
│   ├── config.py        # Configuration management
│   └── main.py          # Entry point
├── database/
│   ├── init.sql         # Initial schema
│   └── migrations/      # Schema migrations
├── n8n/                # n8n workflow exports
├── tests/
│   ├── test_agents.py
│   ├── test_extractors.py
│   └── conftest.py      # pytest fixtures
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Additional Resources

- **Architecture Documentation**: See `/document-organizer-v2/ARCHITECTURE.md` for detailed system design
- **n8n Workflows**: See `/document-organizer-v2/n8n/README.md` for workflow documentation
- **Organize Agent Details**: See `/document-organizer-v2/ORGANIZE_AGENT_README.md` for AI decision-making logic

---

## Final Notes

When GitHub Copilot generates code for DocOrganiser:

1. ✅ **Apply async/await patterns** - All I/O must be asynchronous
2. ✅ **Use structured logging** - Always include contextual data
3. ✅ **Implement comprehensive error handling** - Never fail silently
4. ✅ **Follow the agent architecture** - Inherit from BaseAgent
5. ✅ **Store decisions in database** - All LLM decisions must be persisted
6. ✅ **Support test mode** - Always provide dry-run capability
7. ✅ **Add type hints** - Full type coverage for better IDE support
8. ✅ **Document complex logic** - Include docstrings and comments where needed

If uncertain about implementation details, refer to existing agent implementations or ask for clarification.
