# =============================================================================
# Document Organizer v2 - Processor Container
# =============================================================================

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PDF processing
    poppler-utils \
    # Office document processing
    pandoc \
    libreoffice-writer-nogui \
    libreoffice-calc-nogui \
    libreoffice-impress-nogui \
    # General utilities
    curl \
    unzip \
    zip \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY database/ ./database/

# Security: Create non-root user
RUN groupadd --gid 1000 docorg && \
    useradd --uid 1000 --gid docorg --shell /bin/bash --create-home docorg

# Create data directories and set ownership
RUN mkdir -p /data/input /data/source /data/working /data/output /data/reports && \
    chown -R docorg:docorg /data /app

# Set environment defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO

# Security: Switch to non-root user
USER docorg

# Health check - verify application can start
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from src.config import get_settings; get_settings()" || exit 1

# Default command
CMD ["python", "-m", "src.main"]
